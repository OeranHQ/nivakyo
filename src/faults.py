"""Synthetic first-dispatch faults and independent verification regimes."""
from enum import Enum


class Fault(str, Enum):
    CLEAR_SUCCESS = 'clear_success'
    CLEAR_FAILURE = 'clear_failure'
    PRECOMMIT_FAILURE = 'precommit_failure'
    LOST_ACK = 'lost_ack'
    LATE_COMMIT = 'late_commit'
    PARTIAL_RESPONSE = 'partial_response'


class Verification(str, Enum):
    NONE = 'none'
    AUTHORITATIVE = 'authoritative'
    STALE = 'stale'


def timeout_observation():
    # No fault/schedule/hidden state identifiers in an ambiguous observation.
    return {'status': 'timeout',
            'message': 'Acknowledgement unavailable; execution outcome unknown'}


def partial_observation():
    # The response is truncated, not the execution. The raw bytes are invalid JSON.
    return {'status': 'partial_response', 'raw': '{"status":"ok","effect":'}
