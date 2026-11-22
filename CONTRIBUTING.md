# Contributing

Use Python 3.9+ from the repository root. Offline development requires no package installation.

```sh
make setup
make test
make demo
make validate
```

`make setup` configures `core.hooksPath=.githooks` in this clone. Git does not automatically enable repository hooks when cloning, so repeat setup in each clone. CI checks public history independently.

## Focused changes

Use one purpose per commit. Examples: `feat: add settled lookup semantics`, `fix: reject invalid evidence references`, `test: cover retry after rejection`, `docs: explain trace provenance`. Keep behavior, tests, evidence additions and documentation in separate reviewable commits when they can stand independently. Include why the change matters and what checks passed.

Do not rewrite or replace existing evaluation traces to improve results. Additional collections need distinct output paths and explicit provenance. Live inference consumes quota; offline replay does not count as another model sample.

## Publication boundary

Planned phases, schedules, roadmaps and local phase review records remain local, even when a future task asks to push. Store them under `.local/`. The ignore rules are backed by staged-file and full-history checks: deleting a protected file in a later commit is insufficient because the original content would remain in history.

```sh
python3 scripts/check_publication.py --staged
python3 scripts/check_publication.py --ref HEAD
```

Do not force-add protected files or bypass hooks. If checks fail, remove the protected material from the unpublished history while preserving a local copy. Never force-push shared history as a routine fix.

## Evidence review

Read tool observations before judging report support; compare with private truth separately. Record reviewer provenance honestly. AI-assisted trace review is not independent human annotation. A truthful claim can be unsupported if another state yields the same observations.
