"""Crash-conservative experiment collection with SQLite call reservations.

The legacy runner and frozen evidence retain their original behavior. This runner
uses the separate service environment and public-only reporting forks.
"""
import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from src.action_scorer import score_action
from src.branching import FrozenPrefix, action_request
from src.ledger import canonical
from src.providers import ProviderFailure, create
from src.worlds import CompatibleWorlds, Goal, WorldSpec


class BudgetStop(RuntimeError):
    pass


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_fingerprint():
    root = Path(__file__).resolve().parent
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*.py'))}


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _integer(value, minimum=1, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid integer limit')


def preflight(manifest, live=False):
    """Pure validation plus credential-presence checks; never calls an endpoint."""
    if manifest.get('schema_version') != 1 or not manifest.get('episodes'):
        raise ValueError('Missing manifest schema or episodes')
    limits = manifest['limits']
    for key in ('max_calls', 'max_input_tokens', 'max_output_tokens', 'max_total_tokens', 'max_action_turns'):
        _integer(limits[key])
    _integer(limits['max_attempts_per_call'], maximum=3)
    _integer(limits['budget_micro_usd'], minimum=0)
    if limits['max_action_turns'] > 30:
        raise ValueError('Action turn limit exceeds 30')
    models = manifest['models']
    if not models:
        raise ValueError('No models')
    for name, model in models.items():
        if not name or type(model['model_id']) is not str or not model['model_id'].strip():
            raise ValueError('Exact requested model ID is required')
        prices = model['prices']
        for field in ('input_usd_per_million', 'output_usd_per_million'):
            rate = Decimal(str(prices[field]))
            if not rate.is_finite() or rate < 0:
                raise ValueError('Invalid price')
        if model['adapter'] == 'fixture':
            if any(Decimal(str(prices[k])) != 0 for k in ('input_usd_per_million', 'output_usd_per_million')):
                raise ValueError('Fixtures cannot incur API prices')
            if live:
                raise ValueError('Fixture model in live manifest')
            continue
        if model['adapter'] not in ('openai-chat', 'local-chat'):
            raise ValueError('Unsupported adapter')
        # Construction validates URL without reading credentials or dispatching.
        from src.providers import ChatProvider
        ChatProvider(model)
        _integer(model['timeout_seconds'], maximum=180)
        if model['output_token_field'] not in ('max_tokens', 'max_completion_tokens'):
            raise ValueError('Unsupported output token parameter')
        if type(model['unsupported_options']) is not list or not model['server_version']:
            raise ValueError('Missing provider provenance')
        settings = model.get('settings', {})
        if set(settings) - {'temperature', 'top_p', 'seed', 'reasoning_effort'}:
            raise ValueError('Unsupported provider setting')
        if model['adapter'] == 'local-chat' and not all(model.get(k) for k in
                ('weights_revision', 'tokenizer_revision', 'quantization', 'chat_template_sha256')):
            raise ValueError('Local weight/tokenizer/template provenance required')
        if live:
            token_bound = model.get('token_bound', {})
            if token_bound.get('method') != 'utf8_bytes' or not token_bound.get('audit_reference'):
                raise ValueError('Audited tokenizer and chat-envelope upper bound required')
            _integer(token_bound['envelope_tokens'], minimum=0)
            if model.get('api_key_env') and not os.environ.get(model['api_key_env']):
                raise ValueError('Required credential is absent')
            if model['adapter'] == 'openai-chat' and not model.get('api_key_env'):
                raise ValueError('Remote credential variable required')
            age = (datetime.now(timezone.utc).date() - date.fromisoformat(prices['checked_on'])).days
            if not 0 <= age <= 1 or not prices.get('source_url', '').startswith('https://'):
                raise ValueError('Current official pricing provenance required')
            if not prices.get('includes_reasoning_and_uncached_input'):
                raise ValueError('Reservation prices must cover reasoning and uncached input')
    if live and not manifest.get('authorization', {}).get('reference'):
        raise ValueError('Explicit bounded live spending authorization is missing')
    if live and manifest['authorization'].get('budget_micro_usd') != limits['budget_micro_usd']:
        raise ValueError('Authorized and configured budget differ')
    ids = set()
    for episode in manifest['episodes']:
        eid = episode['episode_id']
        if type(eid) is not str or not eid or eid in ids or len(eid) > 120 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in eid):
            raise ValueError('Episode IDs must be unique safe filenames')
        ids.add(eid)
        if episode['model'] not in models:
            raise ValueError('Unknown model in episode')
        goal = Goal.create(**episode['goal'])
        specs = tuple(WorldSpec(**w) for w in episode['worlds'])
        worlds = CompatibleWorlds(goal, specs)
        if episode['actual_world'] not in {s.world_id for s in worlds.specs}:
            raise ValueError('Actual world is not declared')
    return {'episodes': len(ids), 'models': len(models), 'manifest_sha256': sha(manifest),
            'live': live, 'network_requests': 0}


def charge(model, input_tokens, output_tokens):
    prices = model['prices']
    # USD / million tokens numerically equals micro-USD / token.
    return int((Decimal(str(prices['input_usd_per_million'])) * input_tokens +
                Decimal(str(prices['output_usd_per_million'])) * output_tokens).to_integral_value(rounding=ROUND_CEILING))


class Store:
    def __init__(self, directory, manifest):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / '.collector.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError('Another collector owns this run') from None
        self.db = sqlite3.connect(self.directory / 'run.sqlite')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, status TEXT NOT NULL, artifact TEXT);
            CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, episode TEXT NOT NULL, stage TEXT NOT NULL,
                attempt INTEGER NOT NULL, status TEXT NOT NULL, held INTEGER NOT NULL,
                tokens INTEGER NOT NULL, request TEXT NOT NULL, response TEXT, error TEXT);
        ''')
        frozen = canonical(manifest)
        existing = self.db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
        if existing and existing[0] != frozen:
            self.close()
            raise ValueError('Resume manifest differs from the frozen run')
        sources = canonical(source_fingerprint())
        frozen_sources = self.db.execute("SELECT value FROM meta WHERE key='sources'").fetchone()
        if frozen_sources and frozen_sources[0] != sources:
            self.close()
            raise ValueError('Runner sources changed; resume requires the original code')
        if not existing:
            with self.db:
                self.db.executemany('INSERT INTO meta VALUES (?,?)', [
                    ('manifest', frozen), ('sources', sources), ('run_id', str(uuid.uuid4())), ('budget_violation', 'false')])
                self.db.executemany('INSERT INTO episodes VALUES (?,?,NULL)',
                                    [(e['episode_id'], 'queued') for e in manifest['episodes']])
        self.manifest = manifest
        self.run_id = self.db.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0]
        atomic_json(self.directory / 'manifest.json', manifest)

    def close(self):
        self.db.close()
        self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def reserve(self, eid, stage, attempt, request, model):
        limits = self.manifest['limits']
        # For text-only byte-fallback tokenizers, encoded bytes + envelope
        # allowance is conservative. Other tokenizers need an audited bound.
        overhead = model.get('token_bound', {}).get('envelope_tokens', 1024)
        bound = len(canonical(request).encode()) + overhead
        if bound > limits['max_input_tokens']:
            raise BudgetStop('Prompt byte bound exceeds input-token cap')
        reserved_tokens = limits['max_input_tokens'] + limits['max_output_tokens']
        amount = charge(model, limits['max_input_tokens'], limits['max_output_tokens'])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            calls, held, tokens = self.db.execute('SELECT count(*),coalesce(sum(held),0),coalesce(sum(tokens),0) FROM calls').fetchone()
            violation = self.db.execute("SELECT value FROM meta WHERE key='budget_violation'").fetchone()[0]
            if violation == 'true' or calls >= limits['max_calls'] or held + amount > limits['budget_micro_usd'] or tokens + reserved_tokens > limits['max_total_tokens']:
                raise BudgetStop('Global call, token or cost cap reached')
            call_id = str(uuid.uuid4())
            self.db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)',
                (call_id, eid, stage, attempt, 'reserved', amount, reserved_tokens, canonical(request), None, None))
            self.db.commit()
            return call_id
        except BaseException:
            self.db.rollback()
            raise

    def complete(self, call_id, response, model):
        limits = self.manifest['limits']
        counts = (response.input_tokens, response.output_tokens)
        known = all(type(c) is int and c >= 0 for c in counts)
        exceeded = known and (counts[0] > limits['max_input_tokens'] or counts[1] > limits['max_output_tokens'])
        payload = asdict(response)
        with self.db:
            if known:
                amount = charge(model, *counts)
                self.db.execute('UPDATE calls SET status=?,held=?,tokens=?,response=? WHERE id=?',
                                ('succeeded', amount, sum(counts), canonical(payload), call_id))
            else:
                self.db.execute("UPDATE calls SET status='usage_unknown',response=? WHERE id=?", (canonical(payload), call_id))
            if exceeded:
                self.db.execute("UPDATE meta SET value='true' WHERE key='budget_violation'")
        if exceeded:
            raise BudgetStop('Provider exceeded reserved token bounds; collection halted')

    def finish(self, eid, record):
        with self.db:
            self.db.execute('UPDATE episodes SET status=?,artifact=? WHERE id=?',
                            (record['status'], canonical(record), eid))
        atomic_json(self.directory / 'episodes' / (eid + '.json'), record)

    def call(self, provider, eid, stage, request, model):
        for attempt in range(self.manifest['limits']['max_attempts_per_call']):
            call_id = self.reserve(eid, stage, attempt, request, model)
            try:
                response = provider.complete(json.loads(canonical(request)), self.manifest['limits']['max_output_tokens'])
                self.complete(call_id, response, model)
                return response
            except ProviderFailure:
                # Billing is unknown after transport failure. Keep the full reservation.
                with self.db:
                    self.db.execute("UPDATE calls SET status='error',error='provider_failure' WHERE id=?", (call_id,))
        raise ProviderFailure('Bounded provider attempts exhausted')

    def recover(self):
        # Never redispatch an interrupted episode: remote success may be unknown.
        for row in self.db.execute("SELECT id FROM episodes WHERE status='running'").fetchall():
            eid = row['id']
            self.finish(eid, {'episode_id': eid, 'run_id': self.run_id,
                'status': 'interrupted', 'reason': 'Crash recovery; no automatic redispatch',
                'calls': [dict(c) for c in self.db.execute('SELECT * FROM calls WHERE episode=?', (eid,))]})

    def export(self):
        episodes = [dict(r) for r in self.db.execute('SELECT id,status FROM episodes ORDER BY id')]
        counts = {}
        for e in episodes:
            counts[e['status']] = counts.get(e['status'], 0) + 1
        calls = [dict(r) for r in self.db.execute('SELECT * FROM calls ORDER BY rowid')]
        summary = {'run_id': self.run_id, 'manifest_sha256': sha(self.manifest),
            'source_fingerprint': json.loads(self.db.execute("SELECT value FROM meta WHERE key='sources'").fetchone()[0]),
            'planned_episodes': len(episodes), 'episode_statuses': counts,
            'provider_attempts': len(calls), 'branch_attempts': {b: sum(c['stage'] == b for c in calls) for b in ('A', 'B')},
            'reserved_or_accounted_micro_usd': sum(c['held'] for c in calls),
            'reserved_or_accounted_tokens': sum(c['tokens'] for c in calls),
            'unresolved_calls': sum(c['status'] == 'reserved' for c in calls),
            'unknown_usage_calls': sum(c['status'] in ('reserved', 'error', 'usage_unknown') for c in calls),
            'budget_violation': self.db.execute("SELECT value FROM meta WHERE key='budget_violation'").fetchone()[0] == 'true',
            'provenance': 'fixture' if all(m['adapter'] == 'fixture' for m in self.manifest['models'].values()) else 'live_inference',
            'episodes': episodes, 'calls': calls}
        atomic_json(self.directory / 'accounting.json', summary)
        # Repair exports if interrupted after committing a terminal record.
        for row in self.db.execute('SELECT id,artifact FROM episodes WHERE artifact IS NOT NULL'):
            atomic_json(self.directory / 'episodes' / (row['id'] + '.json'), json.loads(row['artifact']))
        return summary


def run_episode(store, spec, provider):
    eid = spec['episode_id']
    goal = Goal.create(**spec['goal'])
    worlds = CompatibleWorlds(goal, tuple(WorldSpec(**w) for w in spec['worlds']))
    actual = next(w for w in worlds.specs if w.world_id == spec['actual_world'])
    env = actual.instantiate()
    model = store.manifest['models'][spec['model']]
    decisions, actions = [], []
    record = {'episode_id': eid, 'run_id': store.run_id, 'provenance':
        'fixture' if model['adapter'] == 'fixture' else 'live_inference',
        'status': 'action_limit', 'branches': {}, 'model_config': model,
        'cell': spec.get('cell'), 'goal': goal.public()}
    try:
        for _ in range(store.manifest['limits']['max_action_turns']):
            response = store.call(provider, eid, 'action', action_request(
                goal.public(), worlds.contract, env.evidence, decisions), model)
            try:
                decision = json.loads(response.text)
                if type(decision) is not dict or decision.get('type') not in ('tool', 'stop'):
                    raise ValueError('Invalid action decision')
                if decision['type'] == 'stop':
                    if set(decision) != {'type'}:
                        raise ValueError('Unexpected stop fields')
                    record['status'] = 'completed'
                    break
                if set(decision) != {'type', 'name', 'arguments'} or type(decision['name']) is not str or type(decision['arguments']) is not dict:
                    raise ValueError('Malformed tool action')
            except (ValueError, TypeError):
                record['status'] = 'protocol_error'
                break
            decisions.append(decision)
            actions.append(score_action(worlds, decision['name'], decision['arguments']))
            observation = env.call(decision['name'], decision['arguments'])
            worlds = worlds.observe(decision['name'], decision['arguments'], observation, env.now_ms)
        prefix = FrozenPrefix.freeze(goal.public(), worlds.contract, env.evidence, decisions)
        record.update(prefix_sha256=prefix.sha256, frozen_prefix=prefix.serialized)
        # Store the fork before either report call. Siblings get independent clones.
        atomic_json(store.directory / 'prefixes' / (eid + '.json'),
                    {'prefix_sha256': prefix.sha256, 'serialized': prefix.serialized})
        if record['status'] != 'protocol_error':
            for branch in ('A', 'B'):
                response = store.call(provider, eid, branch, prefix.request(branch), model)
                record['branches'][branch] = {'text': response.text, 'metadata': response.metadata,
                    'prefix_sha256': prefix.sha256, 'request_sha256': sha(prefix.request(branch))}
    except BudgetStop as exc:
        record.update(status='budget_stop', reason=str(exc))
    except ProviderFailure:
        record.update(status='infrastructure_error', reason='Bounded provider attempts exhausted')
    finally:
        record.update(evidence=env.evidence, decisions=decisions, action_assessments=actions)
        # All hidden state lives in the evaluator artifact, never the prefix.
        env.settle()
        record['private_evaluation'] = {'worlds': spec['worlds'], 'actual_world': spec['actual_world'],
            'compatible_world_ids': [w.world_id for w in worlds.specs],
            'settled_result': env.private_result(goal.intent_id, goal.payload),
            'world_set_sha256': worlds.world_set_hash}
    return record


def collect(manifest, directory, live=False, factory=create):
    preflight(manifest, live=live)
    if not live and any(m['adapter'] != 'fixture' for m in manifest['models'].values()):
        raise ValueError('Offline collection requires fixture adapters')
    # A nonempty unrelated directory must never become a run by accident.
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()) and not (directory / 'run.sqlite').exists():
        raise ValueError('Output directory is nonempty and is not a resumable run')
    with Store(directory, manifest) as store:
        store.recover()
        stopped = False
        for spec in manifest['episodes']:
            status = store.db.execute('SELECT status FROM episodes WHERE id=?', (spec['episode_id'],)).fetchone()[0]
            if status != 'queued':
                continue
            if stopped:
                continue
            with store.db:
                store.db.execute("UPDATE episodes SET status='running' WHERE id=?", (spec['episode_id'],))
            record = run_episode(store, spec, factory(manifest['models'][spec['model']]))
            store.finish(spec['episode_id'], record)
            stopped = record['status'] == 'budget_stop'
        return store.export()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.check_only:
        print(json.dumps(preflight(manifest, args.live), indent=2))
    elif args.output is None:
        parser.error('--output is required to collect')
    else:
        summary = collect(manifest, args.output, args.live)
        print(json.dumps({k: v for k, v in summary.items() if k not in ('calls', 'episodes')}, indent=2))


if __name__ == '__main__':
    main()
