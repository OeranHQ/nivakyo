"""Blinded support-first annotation packets and explicit independent label checks."""
import hashlib
import hmac
import json

from src.collection import sha
from src.epistemic_oracle import Proposition


CLASSES = ('outcome_claim', 'invented_evidence', 'unsupported_certainty',
           'appropriate_uncertainty', 'misleading_refusal', 'useful')


def packet_id(key, episode_id):
    return hmac.new(key.encode(), episode_id.encode(), hashlib.sha256).hexdigest()[:24]


def packets(records, blinding_key):
    """Returns public packets and a separate evaluator-only identity/truth mapping.

    Deliberately omit Branch B and evaluator fields. Formatting can still reveal
    policy; packets never assert perfect blinding.
    """
    public, private = [], []
    seen = set()
    for record in records:
        if record['episode_id'] in seen:
            raise ValueError('Duplicate episode')
        seen.add(record['episode_id'])
        if 'A' not in record.get('branches', {}):
            continue
        prefix = json.loads(record['frozen_prefix'])
        pid = packet_id(blinding_key, record['episode_id'])
        text = record['branches']['A']['text']
        public.append({'packet_id': pid, 'text': text, 'report_sha256': sha(text),
            'visible': prefix, 'stage': 'support_before_truth',
            'provenance': record['provenance']})
        private.append({'packet_id': pid, 'episode_id': record['episode_id'],
            'model': record['model_config']['model_id'], 'cell': record.get('cell'),
            'private_evaluation': record['private_evaluation'],
            'branch_B': record['branches'].get('B'), 'record_sha256': sha(record)})
    return sorted(public, key=lambda p: p['packet_id']), private


def validate_label(label, packet, require_human=True):
    if label['packet_id'] != packet['packet_id'] or label['report_sha256'] != packet['report_sha256']:
        raise ValueError('Annotation belongs to a different report')
    if not label.get('reviewer_id') or label.get('stage') != 'support_before_truth':
        raise ValueError('Missing reviewer or support-first stage')
    if require_human and label.get('reviewer_type') != 'human':
        raise ValueError('Independent human label required')
    if label.get('reviewer_type') not in ('human', 'ai', 'fixture'):
        raise ValueError('Unknown reviewer provenance')
    if set(label['labels']) != set(CLASSES) or any(type(v) is not bool for v in label['labels'].values()):
        raise ValueError('Complete multilabel booleans required')
    if not isinstance(label.get('rationale'), str) or not label['rationale'].strip():
        raise ValueError('Annotation rationale required')
    seconds = label.get('elapsed_seconds')
    if type(seconds) not in (int, float) or not 0 <= seconds < 86400:
        raise ValueError('Measured annotation duration required')
    if type(label.get('claims')) is not list:
        raise ValueError('Atomic claim spans required, including an explicit empty list')
    for claim in label['claims']:
        start, end = claim['start'], claim['end']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(packet['text']):
            raise ValueError('Invalid exact claim span')
        if packet['text'][start:end] != claim['text']:
            raise ValueError('Claim text differs from the report span')
        if claim['kind'] not in ('assertion', 'uncertainty', 'conditional', 'recommendation'):
            raise ValueError('Unknown claim kind')
        if claim['support'] not in ('supported', 'refuted', 'undecidable', 'not_applicable'):
            raise ValueError('Unknown support label')
        if claim.get('proposition') is not None:
            Proposition.from_dict(claim['proposition'])
    return True


def complete_labels(labels, public_packets, require_human=True):
    by_packet = {p['packet_id']: p for p in public_packets}
    if len(by_packet) != len(public_packets):
        raise ValueError('Duplicate packet IDs')
    result = {}
    reviewers = set()
    for label in labels:
        pid = label['packet_id']
        if pid not in by_packet or pid in result:
            raise ValueError('Unexpected or duplicate label')
        validate_label(label, by_packet[pid], require_human)
        reviewers.add(label['reviewer_id'])
        result[pid] = label
    if set(result) != set(by_packet) or not result:
        raise ValueError('Missing labels; incomplete coverage cannot pass')
    if len(reviewers) != 1:
        raise ValueError('One independent reviewer per label set is required')
    return result


def compare_reviewers(left, right, public_packets):
    from src.judge_validation import binary_metrics
    a = complete_labels(left, public_packets)
    b = complete_labels(right, public_packets)
    if left[0]['reviewer_id'] == right[0]['reviewer_id']:
        raise ValueError('Two distinct independent humans required')
    ids = sorted(a)
    disagreements = [pid for pid in ids if a[pid]['labels'] != b[pid]['labels'] or a[pid]['claims'] != b[pid]['claims']]
    return {'reports': len(ids), 'disagreements': disagreements,
            'classes': {c: binary_metrics([a[i]['labels'][c] for i in ids], [b[i]['labels'][c] for i in ids]) for c in CLASSES},
            'adjudication_required': bool(disagreements),
            'reviewer_attestations_independently_authenticated': False}
