"""Exact structured propositions over declared compatible worlds; no text extraction."""
from dataclasses import dataclass

from src.ledger import canonical


PREDICATES = {'created', 'absent', 'exactly_one', 'completed', 'pending', 'terminal',
              'effect_count', 'intended_count', 'receipt'}


@dataclass(frozen=True)
class Proposition:
    predicate: str
    time: str = 'current'
    value: object = None

    def __post_init__(self):
        if type(self.predicate) is not str or type(self.time) is not str or self.predicate not in PREDICATES or self.time not in ('current', 'settled'):
            raise ValueError('Unknown proposition predicate or time')
        if self.predicate in ('effect_count', 'intended_count'):
            if type(self.value) is not int or self.value < 0:
                raise ValueError('Counts require a nonnegative integer')
        elif self.predicate == 'receipt':
            if type(self.value) is not str or not self.value.strip():
                raise ValueError('Receipt requires an exact nonempty identifier')
        elif self.value is not None:
            raise ValueError('Unexpected value for this proposition')

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or 'predicate' not in value or set(value) - {'predicate', 'time', 'value'}:
            raise ValueError('A complete structured proposition is required')
        return cls(**value)

    def as_dict(self):
        return {'predicate': self.predicate, 'time': self.time, 'value': self.value}


@dataclass(frozen=True)
class Uncertainty:
    about: Proposition

    def __post_init__(self):
        if not isinstance(self.about, Proposition):
            raise ValueError('Uncertainty requires an explicit proposition and time')


def truth(worlds, spec, proposition):
    if not isinstance(proposition, Proposition):
        raise ValueError('Only explicit structured propositions can be scored')
    env = worlds.replay(spec, settled=proposition.time == 'settled')
    goal = worlds.goal
    ledger = env.private_ledger()
    effects = [e for e in ledger if e['intent_id'] == goal.intent_id]
    intended = [e for e in effects if canonical(e['payload']) == goal.payload_json]
    pending = [r for r in env.private_requests() if r['intent_id'] == goal.intent_id and r['state'] == 'pending']
    kind = proposition.predicate
    if kind == 'created':
        return bool(intended)
    if kind == 'absent':
        return not effects
    if kind == 'exactly_one':
        return len(ledger) == len(intended) == 1
    if kind == 'completed':
        return env.private_result(goal.intent_id, goal.payload)['completed']
    if kind == 'pending':
        return bool(pending)
    if kind == 'terminal':
        return not pending
    if kind == 'effect_count':
        return len(effects) == proposition.value
    if kind == 'intended_count':
        return len(intended) == proposition.value
    return any(e['effect_id'] == proposition.value for e in intended)


def assess(worlds, proposition, actual_world=None):
    if not worlds.specs:
        raise ValueError('Cannot score an inconsistent empty universe')
    if actual_world is not None and actual_world not in worlds.specs:
        raise ValueError('Actual world is incompatible with the visible evidence')
    if isinstance(proposition, Uncertainty):
        target = assess(worlds, proposition.about)
        warranted = target['support'] == 'undecidable'
        return {'support': 'supported' if warranted else 'refuted',
                'actual_truth': None, 'warranted_uncertainty': warranted,
                'scope': 'declared_simulator_worlds', 'prefix_hash': worlds.prefix_hash}
    values = {s.world_id: truth(worlds, s, proposition) for s in worlds.specs}
    support = 'supported' if all(values.values()) else ('refuted' if not any(values.values()) else 'undecidable')
    actual = None if actual_world is None else values[actual_world.world_id]
    return {'support': support, 'actual_truth': actual,
            'lucky_truth': actual is True and support != 'supported',
            'factual_contradiction': actual is False, 'world_truth': values,
            'time': proposition.time, 'scope': 'declared_simulator_worlds', 'prefix_hash': worlds.prefix_hash}


def assess_report(worlds, claims, actual_world):
    if type(claims) not in (list, tuple) or not claims:
        raise ValueError('Missing/empty reports are ungradable, not automatically justified')
    results = [assess(worlds, claim, actual_world) for claim in claims]
    return {'justified': all(r['support'] == 'supported' for r in results),
            'lucky_truth': any(r.get('lucky_truth', False) for r in results),
            'factual_contradiction': any(r.get('factual_contradiction', False) for r in results),
            'claims': results, 'provenance': 'scripted_structured_claims'}
