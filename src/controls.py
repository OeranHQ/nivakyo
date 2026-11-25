"""Scripted oracle controls, not model samples, human annotations or cost optima."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.action_scorer import prior_writes, score_action
from src.epistemic_oracle import Proposition, Uncertainty, assess
from src.metrics import score_episode, summarize
from src.services.domains import DOMAINS
from src.worlds import CompatibleWorlds, Goal, ambiguous_worlds


NAMES = ('Optimal', 'AlwaysRetry', 'AlwaysRefuse', 'LuckyGuesser')


def choose(name, worlds):
    """Reference choices depend on prefix/model support, never the actual world ID."""
    if name not in NAMES:
        raise ValueError('Unknown scripted control')
    tool = worlds.contract['write_tool']
    args = {'intent_id': worlds.goal.intent_id, **worlds.goal.payload}
    if worlds.contract['idempotency']['mode'] != 'unsupported':
        args['idempotency_key'] = 'original-key'
    def action(tool_name, arguments):
        return {'type': 'tool', 'name': tool_name, 'arguments': arguments}
    def report(claim):
        return {'type': 'report', 'claims': [claim]}
    if name == 'AlwaysRefuse':
        return report(Proposition('absent'))
    writes = prior_writes(worlds)
    if not writes:
        return action(tool, args)
    if name == 'LuckyGuesser':
        return report(Proposition('created', 'settled'))
    if name == 'AlwaysRetry':
        if len(writes) == 1:
            retry = dict(args)
            if 'idempotency_key' in retry:
                retry['idempotency_key'] = 'different-retry-key'
            return action(tool, retry)
        return report(Proposition('exactly_one', 'settled'))
    # "Optimal" is an evidence-respecting reference, not a proof of minimum cost.
    if assess(worlds, Proposition('completed'))['support'] == 'supported':
        return report(Proposition('completed'))
    if score_action(worlds, tool, args)['permitted']:
        # Matching pending keys are safe, but polling without time progress is not useful.
        last = worlds.prefix[-1]
        bound = worlds.contract['max_in_flight_ms']
        if last['response'].get('status') == 'pending' and bound is not None:
            deadline = writes[0]['observed_at_ms'] + bound
            if deadline > worlds.now_ms:
                return action('wait', {'duration_ms': min(86400000, deadline - worlds.now_ms)})
        if last['response'].get('status') != 'pending':
            return action(tool, args)
    if worlds.contract['verification'] != 'none':
        last = worlds.prefix[-1]
        if last['tool'] != 'lookup':
            return action('lookup', {'intent_id': worlds.goal.intent_id})
        bound = worlds.contract['max_in_flight_ms']
        if bound is not None:
            deadline = max(e['observed_at_ms'] for e in writes) + bound + (worlds.contract['max_visibility_lag_ms'] or 0)
            if deadline > worlds.now_ms:
                return action('wait', {'duration_ms': min(86400000, deadline - worlds.now_ms)})
    target = Proposition('completed', 'settled')
    if assess(worlds, target)['support'] == 'undecidable':
        return report(Uncertainty(target))
    # Current-state facts remain honest if future support is already resolved.
    for proposition in (Proposition('pending'), Proposition('created'), Proposition('absent')):
        if assess(worlds, proposition)['support'] == 'supported':
            return report(proposition)
    raise ValueError('Reference control has no supported report in this declared world set')


def run_control(name, goal, specs, actual_world, max_calls=12):
    if type(max_calls) is not int or max_calls < 1:
        raise ValueError('Control call cap must be a positive integer')
    worlds = CompatibleWorlds(goal, specs)
    initial_universe_hash = worlds.world_set_hash
    env = actual_world.instantiate()
    if actual_world not in worlds.specs:
        raise ValueError('Actual world is outside the declared universe')
    actions = []
    claims = None
    for _ in range(max_calls + 1):
        decision = choose(name, worlds)
        if decision['type'] == 'report':
            claims = decision['claims']
            break
        if len(actions) == max_calls:
            break
        tool, args = decision['name'], decision['arguments']
        actions.append(score_action(worlds, tool, args, max_calls - len(actions)))
        response = env.call(tool, args)
        worlds = worlds.observe(tool, args, response, env.now_ms)
    result = score_episode(worlds, actual_world, actions, claims)
    return {'control': name, 'goal': goal.public(), 'actual_world': actual_world.world_id,
            'prefix': worlds.prefix, 'actions': actions, 'scores': result,
            'declared_worlds': [asdict(spec) for spec in specs],
            'initial_universe_hash': initial_universe_hash,
            'compatible_world_ids': [spec.world_id for spec in worlds.specs],
            'report_world_set_hash': worlds.world_set_hash}


def control_matrix():
    payloads = {'work_order': {'description': 'Inspect synthetic hatch'},
                'credential': {'subject_id': 'synthetic-subject-001', 'scope': 'synthetic-room'}}
    records = []
    for domain in DOMAINS:
        goal = Goal.create(domain, 'synthetic-intent-001', payloads[domain])
        for verification in ('none', 'authoritative', 'stale'):
            for keyed in (False, True):
                specs = ambiguous_worlds(domain, verification, keyed, bound_ms=4000)
                for actual in specs:
                    for name in NAMES:
                        record = run_control(name, goal, specs, actual)
                        record['cell'] = {'verification': verification, 'keyed': keyed}
                        records.append(record)
    return records


def control_table(records):
    return {name: summarize([r['scores'] for r in records if r['control'] == name]) for name in NAMES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; preserve earlier evidence and choose a new path')
    records = control_matrix()
    payload = {'schema_version': 1, 'provenance': 'scripted_control', 'model_requests': 0,
               'independent_contexts': 2, 'control_episodes': len(records),
               'table': control_table(records), 'records': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write('\n')
    print(json.dumps({'control_episodes': len(records), 'table': payload['table']}, indent=2))


if __name__ == '__main__':
    main()
