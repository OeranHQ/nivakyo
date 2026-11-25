"""Balanced, deterministic, failure-stratified sampling of licensed upstream reports.

Original model-judge labels remain evaluator-only. Human packets contain only
report text, public scenario evidence and opaque identities.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from src.collection import atomic_json, sha


def sample(rows, policies, per_policy, seed, source):
    if type(per_policy) is not int or per_policy < 1 or len(set(policies)) != len(policies):
        raise ValueError('Unique policies and a positive sample size required')
    required = ('release', 'archive_sha256', 'license', 'source_url')
    if any(not source.get(k) for k in required):
        raise ValueError('Versioned licensed source provenance required')
    seen = set()
    for row in rows:
        if row['response_id'] in seen:
            raise ValueError('Duplicate upstream response IDs')
        seen.add(row['response_id'])
        if not row.get('model_judge_label') or type(row.get('response')) is not str:
            raise ValueError('Original report and original labels required')
    selected, counts = [], {}
    for policy in policies:
        strata = defaultdict(list)
        for row in rows:
            if row['condition'] == policy:
                strata[row['category']].append(row)
        if sum(map(len, strata.values())) < per_policy:
            raise ValueError('Insufficient source reports; substitutions must be explicit')
        def rank(row):
            return hashlib.sha256((str(seed) + ':' + row['response_id']).encode()).hexdigest()
        queues = {category: sorted(values, key=rank) for category, values in strata.items()}
        chosen = []
        while len(chosen) < per_policy:
            for category in sorted(queues):
                if queues[category] and len(chosen) < per_policy:
                    chosen.append(queues[category].pop(0))
        selected.extend(chosen)
        counts[policy] = {category: sum(r['category'] == category for r in chosen) for category in sorted(strata)}
    return {'source': source, 'seed': seed, 'selection': 'round_robin_category_sha256_rank_v1',
            'source_rows_sha256': sha(rows), 'policies': counts, 'reports': selected,
            'sample_sha256': sha(selected), 'substitutions': [],
            'human_annotation_status': 'not_started', 'independent_validation': False,
            'inference_limit': 'Balanced non-proportional subset; no population prevalence estimate without weights.'}


def blind(frozen, scenarios, blinding_key):
    from src.annotation import packet_id
    result, mapping = [], []
    for row in frozen['reports']:
        sid = row['scenario_id']
        if sid not in scenarios:
            raise ValueError('Original visible scenario evidence unavailable')
        scenario = scenarios[sid]
        # Upstream field mapping must be reviewed, never pass the full scenario.
        visible = {k: scenario[k] for k in ('user_request', 'tool_name', 'tool_result')}
        pid = packet_id(blinding_key, row['response_id'])
        result.append({'packet_id': pid, 'text': row['response'], 'report_sha256': sha(row['response']),
            'visible': visible, 'stage': 'support_before_truth', 'provenance': 'released_upstream_model_response'})
        mapping.append({'packet_id': pid, 'original': row})
    return sorted(result, key=lambda r: r['packet_id']), mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; preserve the frozen sample')
    config = json.loads(args.config.read_text())
    rows = [json.loads(line) for line in Path(config['input']).read_text().splitlines()]
    result = sample(rows, config['policies'], config['per_policy'], config['seed'], config['source'])
    atomic_json(args.output, result)
    print(json.dumps({'reports': len(result['reports']), 'strata': result['policies'],
                      'sample_sha256': result['sample_sha256']}, indent=2))


if __name__ == '__main__':
    main()
