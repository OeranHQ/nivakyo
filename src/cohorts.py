"""Deterministically expand a declared synthetic experiment design, without inference."""
import argparse
import itertools
import json
from dataclasses import asdict
from pathlib import Path

from src.collection import atomic_json, preflight, sha
from src.worlds import WorldSpec, ambiguous_worlds


def expand(design):
    episodes = []
    factors = (design['contexts'], design['configurations'], list(design['models']), range(design['repetitions']))
    for context, configuration, model, repetition in itertools.product(*factors):
        if configuration['fault'] in ('precommit_failure', 'lost_ack', 'late_commit'):
            specs = ambiguous_worlds(context['domain'], configuration['verification'],
                configuration.get('keyed', False), bound_ms=configuration.get('bound_ms'))
        else:
            specs = (WorldSpec(configuration['fault'], context['domain'], configuration['fault'],
                verification=configuration['verification'], keyed=configuration.get('keyed', False),
                bound_ms=configuration.get('bound_ms')),)
        cell = {'context': context['id'], 'configuration': configuration['id'],
                'model': model, 'repetition': repetition}
        episodes.append({'episode_id': 'ep-' + sha(cell)[:24], 'model': model,
            'goal': {'domain': context['domain'], 'intent_id': context['intent_id'], 'payload': context['payload']},
            'worlds': [asdict(w) for w in specs], 'actual_world': configuration['fault'], 'cell': cell})
    result = {'schema_version': 1, 'models': design['models'], 'limits': design['limits'],
              'episodes': episodes, 'design_sha256': sha(design),
              'authorization': design.get('authorization', {})}
    preflight(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; preserve the previous frozen manifest')
    manifest = expand(json.loads(args.design.read_text()))
    atomic_json(args.output, manifest)
    print(json.dumps({'episodes': len(manifest['episodes']), 'manifest_sha256': sha(manifest)}, indent=2))


if __name__ == '__main__':
    main()
