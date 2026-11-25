"""Append-only evaluator records; mutable payloads never escape by reference."""
import json
from dataclasses import dataclass

from src.clock import milliseconds


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class Effect:
    effect_id: str
    request_id: str
    domain: str
    intent_id: str
    payload_json: str
    committed_at_ms: int
    visible_at_ms: int

    def receipt(self):
        return {'effect_id': self.effect_id, 'intent_id': self.intent_id,
                'payload': json.loads(self.payload_json)}

    def evaluation_record(self):
        return {**self.receipt(), 'request_id': self.request_id, 'domain': self.domain,
                'committed_at_ms': self.committed_at_ms, 'visible_at_ms': self.visible_at_ms}


class ExecutionLedger:
    def __init__(self):
        self._effects = []

    @property
    def effects(self):
        return tuple(self._effects)

    def commit(self, request_id, domain, prefix, intent_id, payload, at_ms, lag_ms):
        milliseconds(at_ms)
        milliseconds(lag_ms)
        if self._effects and at_ms < self._effects[-1].committed_at_ms:
            raise ValueError('Commit times must be monotonic')
        if any(e.request_id == request_id for e in self._effects):
            raise ValueError('A request cannot commit twice')
        effect = Effect('%s-%06d' % (prefix, len(self._effects) + 1), request_id,
                        domain, intent_id, canonical(payload), at_ms, at_ms + lag_ms)
        self._effects.append(effect)
        return effect
