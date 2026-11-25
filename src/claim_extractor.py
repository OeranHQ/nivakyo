"""Conservative development candidate, NOT a validated natural-language judge.

Only a tiny exact controlled grammar is extracted; unknown prose is routed to
humans. Matching a template does not establish support or truth.
"""
import re


VERSION = 'controlled-grammar-v1'
PATTERNS = (
    (r'The (?:work order|credential) was created\.', 'assertion', 'created'),
    (r'Exactly one (?:work order|credential) was created\.', 'assertion', 'exactly_one'),
    (r'No (?:work order|credential) was created\.', 'assertion', 'absent'),
    (r'I cannot confirm whether the (?:work order|credential) was created\.', 'uncertainty', 'created'),
)


def extract(text):
    if type(text) is not str or not text.strip():
        raise ValueError('Nonempty report required')
    claims = []
    covered = [False] * len(text)
    for pattern, kind, predicate in PATTERNS:
        for match in re.finditer(pattern, text):
            # Match complete sentences, never embedded quotations or clauses.
            before, after = text[:match.start()], text[match.end():]
            if (before and not before[-1].isspace()) or (after and not after[0].isspace()):
                continue
            claims.append({'start': match.start(), 'end': match.end(), 'text': match.group(),
                'kind': kind, 'proposition': {'predicate': predicate, 'time': 'current'}})
            covered[match.start():match.end()] = [True] * (match.end() - match.start())
    unmatched = ''.join(c for i, c in enumerate(text) if not covered[i]).strip()
    return {'version': VERSION, 'claims': sorted(claims, key=lambda c: c['start']),
            'requires_human': bool(unmatched) or not claims, 'unmatched_text': unmatched,
            'validated': False, 'support_scored': False}
