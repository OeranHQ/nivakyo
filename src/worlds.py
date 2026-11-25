"""Evaluator-only replay over an explicit finite universe of synthetic worlds."""
import hashlib
import json
from dataclasses import asdict, dataclass

from src.clock import milliseconds
from src.contracts import KeyContract
from src.faults import Fault, Verification
from src.ledger import canonical
from src.services import ServiceEnvironment
from src.services.domains import DOMAINS


class InconsistentEvidence(ValueError):
    """No modeled world matches the full public action/observation prefix."""


@dataclass(frozen=True)
class Goal:
    domain: str
    intent_id: str
    payload_json: str

    def __post_init__(self):
        if self.domain not in DOMAINS:
            raise ValueError('Unknown goal domain')
        payload = json.loads(self.payload_json)
        DOMAINS[self.domain].goal(self.intent_id, payload)
        object.__setattr__(self, 'payload_json', canonical(payload))

    @classmethod
    def create(cls, domain, intent_id, payload):
        return cls(domain, intent_id, canonical(payload))

    @property
    def payload(self):
        return json.loads(self.payload_json)

    def public(self):
        return {'domain': self.domain, 'intent_id': self.intent_id, 'payload': self.payload}


@dataclass(frozen=True)
class WorldSpec:
    world_id: str
    domain: str
    fault: str
    verification: str = 'authoritative'
    keyed: bool = False
    retention_ms: object = None
    delay_ms: int = 4000
    lag_ms: int = 3000
    bound_ms: object = None

    def __post_init__(self):
        if type(self.world_id) is not str or not self.world_id.strip():
            raise ValueError('World ID must be nonempty')
        self.instantiate()  # Validate every hidden setting, including the public bound.

    def instantiate(self):
        return ServiceEnvironment(self.domain, self.fault, self.verification,
            KeyContract(self.keyed, self.retention_ms), self.delay_ms, self.lag_ms, self.bound_ms)


def ambiguous_worlds(domain, verification='authoritative', keyed=False, retention_ms=None,
                     delay_ms=4000, lag_ms=3000, bound_ms=None):
    return tuple(WorldSpec(f.value, domain, f.value, verification, keyed, retention_ms,
                           delay_ms, lag_ms, bound_ms) for f in
                 (Fault.PRECOMMIT_FAILURE, Fault.LOST_ACK, Fault.LATE_COMMIT))


@dataclass(frozen=True)
class CompatibleWorlds:
    goal: Goal
    specs: tuple
    prefix_json: str = '[]'

    def __post_init__(self):
        object.__setattr__(self, 'specs', tuple(self.specs))
        if not self.specs:
            raise InconsistentEvidence('An empty world set is inconsistent, not proof of support')
        if len({s.world_id for s in self.specs}) != len(self.specs):
            raise ValueError('World IDs must be unique')
        contract = self.specs[0].instantiate().public_contract()
        for spec in self.specs:
            if spec.domain != self.goal.domain or spec.instantiate().public_contract() != contract:
                raise ValueError('Paired worlds require the same domain and public contract')
        prefix = json.loads(self.prefix_json)
        if type(prefix) is not list:
            raise ValueError('Prefix must be an ordered evidence list')
        object.__setattr__(self, 'prefix_json', canonical(prefix))
        for spec in self.specs:
            self.replay(spec)

    @property
    def prefix(self):
        return json.loads(self.prefix_json)

    @property
    def contract(self):
        return self.specs[0].instantiate().public_contract()

    @property
    def now_ms(self):
        return self.prefix[-1]['observed_at_ms'] if self.prefix else 0

    def agent_view(self):
        return {'goal': self.goal.public(), 'contract': self.contract,
                'now_ms': self.now_ms, 'evidence': self.prefix}

    @property
    def world_set_hash(self):
        """Evaluator provenance only; never add this hidden-model digest to prompts."""
        return hashlib.sha256(canonical([asdict(s) for s in self.specs]).encode()).hexdigest()

    @property
    def prefix_hash(self):
        return hashlib.sha256(canonical(self.agent_view()).encode()).hexdigest()

    def replay(self, spec, settled=False):
        """Return a fresh evaluator instance; never expose it to a provider."""
        if spec not in self.specs:
            raise ValueError('Actual/replayed world must be compatible with this prefix')
        env = spec.instantiate()
        for event in self.prefix:
            if type(event) is not dict or set(event) != {'tool', 'arguments', 'observed_at_ms', 'response'}:
                raise ValueError('Malformed evidence event')
            env.call(event['tool'], event['arguments'])
            if canonical(env.evidence[-1]) != canonical(event):
                raise InconsistentEvidence('A prefix observation does not match its replay')
        if settled:
            env.settle()
        return env

    def partition(self, name, arguments):
        """Apply the SAME next action; split only on full returned observation bytes."""
        groups = {}
        for spec in self.specs:
            env = self.replay(spec)
            env.call(name, arguments)
            event = env.evidence[-1]
            key = canonical(event)
            groups.setdefault(key, []).append(spec)
        return {key: CompatibleWorlds(self.goal, tuple(specs), canonical(self.prefix + [json.loads(key)]))
                for key, specs in groups.items()}

    def observe(self, name, arguments, response, observed_at_ms=None):
        if observed_at_ms is not None:
            milliseconds(observed_at_ms)
        matches = []
        for event_json, group in self.partition(name, arguments).items():
            event = json.loads(event_json)
            if canonical(event['response']) == canonical(response) and (
                    observed_at_ms is None or event['observed_at_ms'] == observed_at_ms):
                matches.append(group)
        if len(matches) != 1:
            raise InconsistentEvidence('Observed response/time matches no unique replay partition')
        return matches[0]
