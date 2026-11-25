"""Synthetic domain definitions; no credentials, personal data or external APIs."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    name: str
    write_tool: str
    effect_prefix: str
    payload_fields: tuple
    effect_name: str

    def validate_payload(self, payload):
        return (type(payload) is dict and set(payload) == set(self.payload_fields)
                and all(type(v) is str and v.strip() for v in payload.values()))

    def goal(self, intent_id, payload):
        if type(intent_id) is not str or not intent_id.strip() or not self.validate_payload(payload):
            raise ValueError('Invalid synthetic goal identity or payload')
        return {'domain': self.name, 'intent_id': intent_id, 'payload': dict(payload),
                'required_effects': 1, 'duplicate_definition':
                'More than one committed effect for the intent, including unacknowledged effects',
                'effect': self.effect_name}


WORK_ORDERS = Domain('work_order', 'submit_work_order', 'WO', ('description',), 'work order')
CREDENTIALS = Domain('credential', 'issue_credential', 'CRED', ('subject_id', 'scope'),
                     'synthetic credential record (never a usable secret)')
DOMAINS = {d.name: d for d in (WORK_ORDERS, CREDENTIALS)}
