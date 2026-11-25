"""Evidence-accounted summaries; no empirical conclusions from missing human labels."""
import json

from src.annotation import complete_labels
from src.epistemic_oracle import Proposition, Uncertainty, assess
from src.metrics import score_episode, summarize
from src.worlds import CompatibleWorlds, Goal, WorldSpec


def reconstruct(record):
    private = record['private_evaluation']
    goal = Goal.create(**record['goal'])
    worlds = CompatibleWorlds(goal, tuple(WorldSpec(**w) for w in private['worlds']))
    actual = next(w for w in worlds.specs if w.world_id == private['actual_world'])
    for event in record['evidence']:
        worlds = worlds.observe(event['tool'], event['arguments'], event['response'], event['observed_at_ms'])
    return worlds, actual


def diagnostic(record):
    if 'B' not in record.get('branches', {}):
        return {'status': 'missing'}
    try:
        response = json.loads(record['branches']['B']['text'])
        if type(response) is not dict or set(response) != {'claims', 'uncertainty'}:
            raise ValueError('Invalid diagnostic shape')
        if any(type(response[k]) is not list for k in response):
            raise ValueError('Expected proposition lists')
        claims = [Proposition.from_dict(p) for p in response['claims']]
        uncertainty = [Uncertainty(Proposition.from_dict(p)) for p in response['uncertainty']]
        if not claims and not uncertainty:
            raise ValueError('Empty diagnostic')
        worlds, actual = reconstruct(record)
        return {'status': 'structured', 'assessments': [assess(worlds, c, actual) for c in claims + uncertainty],
                'not_a_belief_probe': True}
    except (ValueError, TypeError, KeyError):
        return {'status': 'protocol_error'}


def summarize_labeled(records, public_packets, labels):
    mapping = complete_labels(labels, public_packets)
    by_report_hash = {}
    for p in public_packets:
        # Packet IDs are mapped externally; identical texts are allowed.
        by_report_hash.setdefault(p['report_sha256'], []).append(p)
    scored, unscored = [], []
    for packet in public_packets:
        label = mapping[packet['packet_id']]
        matches = [r for r in records if r.get('branches', {}).get('A', {}).get('text') == packet['text']
                   and json.loads(r.get('frozen_prefix', '{}')) == packet['visible']]
        if len(matches) != 1:
            raise ValueError('Packet identity is ambiguous; supply an explicit one-to-one mapping')
        record = matches[0]
        claims = []
        for c in label['claims']:
            if c.get('proposition') and c['kind'] in ('assertion', 'uncertainty'):
                p = Proposition.from_dict(c['proposition'])
                claims.append(Uncertainty(p) if c['kind'] == 'uncertainty' else p)
        if not claims:
            unscored.append(record['episode_id'])
            continue
        worlds, actual = reconstruct(record)
        scores = score_episode(worlds, actual, record['action_assessments'], claims)
        scores['provenance'] = 'human_extracted_claims_deterministic_support'
        scored.append(scores)
    summary = summarize(scored) if scored else None
    if summary:
        summary.update(provenance='human_extracted_claims_deterministic_support', model_requests=None)
    return {'labeled_reports': len(mapping), 'structured_scorable_reports': len(scored),
            'reports_without_structured_claims': unscored, 'scored_subset': summary,
            'quadrants_cover_all_attempts': False,
            'measured_annotation_seconds': sum(l['elapsed_seconds'] for l in labels)}
