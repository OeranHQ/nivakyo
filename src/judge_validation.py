"""Strict held-out multilabel comparison; missing/degenerate evidence cannot pass."""
import math

from src.annotation import CLASSES


def binary_metrics(gold, predicted):
    if not gold or len(gold) != len(predicted) or any(type(v) is not bool for v in gold + predicted):
        raise ValueError('Aligned nonempty boolean labels required')
    n = len(gold)
    tp = sum(g and p for g, p in zip(gold, predicted))
    tn = sum(not g and not p for g, p in zip(gold, predicted))
    fp = sum(not g and p for g, p in zip(gold, predicted))
    fn = sum(g and not p for g, p in zip(gold, predicted))
    prevalence, predicted_rate = sum(gold) / n, sum(predicted) / n
    observed = (tp + tn) / n
    expected = prevalence * predicted_rate + (1 - prevalence) * (1 - predicted_rate)
    return {'n': n, 'tp': tp, 'tn': tn, 'fp': fp, 'fn': fn,
        'gold_prevalence': prevalence, 'predicted_prevalence': predicted_rate,
        'rate_bias': predicted_rate - prevalence,
        'kappa': None if math.isclose(expected, 1) else (observed - expected) / (1 - expected),
        'precision': None if tp + fp == 0 else tp / (tp + fp),
        'recall': None if tp + fn == 0 else tp / (tp + fn)}


def validate_automation(development, validation, predictions, min_reports, min_kappa, max_bias):
    """Thresholds are explicit caller-supplied screening rules, never proof of validity."""
    if min_reports < 1 or not 0 <= min_kappa <= 1 or not 0 <= max_bias <= 1:
        raise ValueError('Invalid validation thresholds')
    def keyed(rows):
        result = {}
        for r in rows:
            if r['report_id'] in result:
                raise ValueError('Duplicate report IDs')
            if set(r['labels']) != set(CLASSES) or any(type(v) is not bool for v in r['labels'].values()):
                raise ValueError('Complete multilabel predictions required')
            result[r['report_id']] = r
        return result
    dev, held, pred = keyed(development), keyed(validation), keyed(predictions)
    if set(dev) & set(held):
        raise ValueError('Development/validation report overlap')
    dev_hashes = {r['report_sha256'] for r in development}
    held_hashes = {r['report_sha256'] for r in validation}
    if dev_hashes & held_hashes:
        raise ValueError('Duplicate report content across splits')
    if {r['context_id'] for r in development} & {r['context_id'] for r in validation}:
        raise ValueError('Development/validation context overlap')
    if set(held) != set(pred) or not held:
        raise ValueError('Predictions must cover every validation report exactly')
    for row in validation:
        if row.get('reviewer_type') != 'human' or len(set(row.get('independent_reviewers', []))) < 2 or not row.get('adjudicated'):
            raise ValueError('Disjoint independently human-reviewed reference labels required')
        if pred[row['report_id']]['report_sha256'] != row['report_sha256']:
            raise ValueError('Prediction content hash mismatch')
    ids = sorted(held)
    metrics = {c: binary_metrics([held[i]['labels'][c] for i in ids], [pred[i]['labels'][c] for i in ids]) for c in CLASSES}
    enough = len(ids) >= min_reports
    passes = enough and all(m['kappa'] is not None and m['kappa'] >= min_kappa and abs(m['rate_bias']) < max_bias for m in metrics.values())
    return {'reports': len(ids), 'independent_contexts': len({r['context_id'] for r in validation}),
        'classes': metrics, 'screen_pass': passes,
        'rare_critical_failures_require_manual_review': True,
        'grading_route': 'screened_candidate_plus_human_review' if passes else 'full_manual_review',
        'limits': 'Self-declared reviewer provenance; formatting leakage and claim-span errors require separate review.'}
