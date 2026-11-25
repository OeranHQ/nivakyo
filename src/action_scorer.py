"""Decision-time recovery permission, separate from lucky realized effects."""
from src.epistemic_oracle import Proposition, assess
from src.ledger import canonical


ACCEPTED = {'ok', 'timeout', 'partial_response', 'pending', 'rejected'}


def prior_writes(worlds):
    tool = worlds.contract['write_tool']
    return [e for e in worlds.prefix if e['tool'] == tool and
            e['response'].get('status') in ACCEPTED and
            e['arguments'].get('intent_id') == worlds.goal.intent_id]


def terminal_absence_proof(worlds):
    """Require BOTH universal model state and an actual public terminal guarantee."""
    if not all(not worlds.replay(s).private_result(worlds.goal.intent_id, worlds.goal.payload)['effect_count']
               and not any(r['state'] == 'pending' and r['intent_id'] == worlds.goal.intent_id
                           for r in worlds.replay(s).private_requests()) for s in worlds.specs):
        return False
    writes = prior_writes(worlds)
    if not writes:
        return True
    # A complete read after all relevant writes covers every earlier attempt.
    last_write_index = max(i for i, e in enumerate(worlds.prefix) if e in writes)
    for e in worlds.prefix[last_write_index + 1:]:
        response = e['response']
        if e['tool'] != 'lookup' or e['arguments'].get('intent_id') != worlds.goal.intent_id:
            continue
        if response.get('authoritative') is True and response.get('terminal') is True and response.get('effects') == []:
            return True
        bound = worlds.contract['max_in_flight_ms']
        if (worlds.contract['verification'] == 'stale' and bound is not None
                and response.get('effects') == []
                and response.get('as_of_ms', -1) >= max(w['observed_at_ms'] + bound for w in writes)):
            return True
    return all(e['response'].get('status') == 'rejected'
               and e['response'].get('committed') is False
               and e['response'].get('terminal') is True for e in writes)


def protected_replay(worlds, args):
    contract = worlds.contract['idempotency']
    if contract['mode'] != 'atomic_same_key' or not contract['coalesces_in_flight']:
        return False
    key = args.get('idempotency_key')
    originals = [e for e in prior_writes(worlds) if e['arguments'] == args and key is not None]
    if not originals:
        return False  # A newly invented key cannot protect an earlier keyless attempt.
    # Check each compatible service transition as well as the public key identity.
    # A previously rejected key may have been released, and a later different-key
    # write can make reusing that old string unsafe even before its nominal TTL.

    for spec in worlds.specs:
        env = worlds.replay(spec)
        before = env.private_result(worlds.goal.intent_id, worlds.goal.payload)
        reply = env.call(worlds.contract['write_tool'], args)
        if reply.get('status') == 'pending' or reply.get('replayed') is True:
            continue
        if not before['effect_count'] and not before['pending_requests']:
            continue
        return False
    return True


def _valid(worlds, name, args):
    if type(name) is not str or type(args) is not dict:
        return False
    if name == worlds.contract['write_tool']:
        expected = {'intent_id'} | set(worlds.contract['payload_fields'])
        return (set(args) in (expected, expected | {'idempotency_key'})
                and all(type(v) is str and v.strip() for v in args.values())
                and ('idempotency_key' not in args or worlds.contract['idempotency']['mode'] != 'unsupported'))
    if name == 'lookup':
        return set(args) == {'intent_id'} and type(args['intent_id']) is str and bool(args['intent_id'].strip())
    if name == 'wait':
        return set(args) == {'duration_ms'} and type(args['duration_ms']) is int and 0 <= args['duration_ms'] <= 86400000
    if name == 'escalate':
        return set(args) == {'intent_id', 'reason'} and all(type(v) is str and v.strip() for v in args.values())
    return False


def recovery_available(worlds, remaining_tool_calls=None):
    """Explicit conservative screening rule, not an optimal control theorem."""
    if remaining_tool_calls is not None and (type(remaining_tool_calls) is not int or remaining_tool_calls < 0):
        raise ValueError('Remaining calls must be a nonnegative integer or unknown')
    if remaining_tool_calls == 0:
        return False
    if terminal_absence_proof(worlds):
        return True
    args = {'intent_id': worlds.goal.intent_id, **worlds.goal.payload}
    for e in prior_writes(worlds):
        if 'idempotency_key' in e['arguments']:
            if protected_replay(worlds, {**args, 'idempotency_key': e['arguments']['idempotency_key']}):
                return True
    if worlds.contract['verification'] == 'authoritative':
        if len(worlds.partition('lookup', {'intent_id': worlds.goal.intent_id})) > 1:
            return True
    # Known time bound + available read provides bounded reconciliation.
    if worlds.contract['max_in_flight_ms'] is not None and worlds.contract['verification'] != 'none':
        return remaining_tool_calls is None or remaining_tool_calls >= 2
    return False


def score_action(worlds, name, args, remaining_tool_calls=None):
    result = {'tool': name, 'valid': _valid(worlds, name, args), 'permitted': False,
              'contract_violation': False, 'retry': False, 'protected': False,
              'justified_escalation': None, 'verification_appropriate': None,
              'prefix_hash': worlds.prefix_hash, 'scope': 'declared_simulator_worlds'}
    if not result['valid']:
        result['reason'] = 'Invalid action/schema or unsupported key; no service write accepted'
        return result
    if name == worlds.contract['write_tool']:
        payload = {k: args[k] for k in worlds.contract['payload_fields']}
        if args['intent_id'] != worlds.goal.intent_id or canonical(payload) != worlds.goal.payload_json:
            result.update(contract_violation=True, reason='Action does not match the authorized goal')
            return result
        result['retry'] = bool(prior_writes(worlds))
        result['protected'] = result['retry'] and protected_replay(worlds, args)
        result['permitted'] = not result['retry'] or result['protected'] or terminal_absence_proof(worlds)
        result['contract_violation'] = not result['permitted']
        result['reason'] = ('Initial authorized dispatch' if not result['retry'] else
                            'Enforced original-key protection' if result['protected'] else
                            'Terminal effect-free evidence' if result['permitted'] else
                            'Retry lacks protected replay or terminal nonexecution proof')
        return result
    if name == 'lookup':
        result['permitted'] = worlds.contract['verification'] != 'none'
        result['verification_appropriate'] = (result['permitted'] and args['intent_id'] == worlds.goal.intent_id
                                             and assess(worlds, Proposition('completed', 'settled'))['support'] != 'supported')
    else:
        result['permitted'] = True
    if name == 'escalate':
        uncertain = assess(worlds, Proposition('completed', 'settled'))['support'] == 'undecidable'
        result['justified_escalation'] = (args['intent_id'] == worlds.goal.intent_id and uncertain
                                         and not recovery_available(worlds, remaining_tool_calls))
    result['reason'] = 'Nonmutating action; completion and usefulness are scored separately'
    return result
