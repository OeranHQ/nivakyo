# Nivakyo repository instructions

Project: **nivakyo.** Tagline: **Know what can be known.** Purpose: AI agent honesty, uncertainty, and evidence-grounded evaluation.

## Working location

This checkout is the authoritative development repository. Run commands from its root. The original evaluation checkout was moved here from the RTC workspace. Do not continue development in the old checkout.

## User's persistent publication restriction

The user explicitly requires planned phases and phase planning/review files to remain LOCAL ONLY, including whenever they later ask to commit or push. A generic request to push does not authorize publishing this material.

- Never add, commit, upload or push `.local/`, planning schedules, roadmaps, phase status files, or the protected planning documents listed in `scripts/check_publication.py`.
- Preserve local-only material. Never delete it merely to make a check pass.
- Never use `git add -f` for protected files, `--no-verify`, or another hook bypass to publish them.
- Never push the preserved pre-migration Git history or its tags. It includes local-only planning documents. Only the new public repository history is eligible for push.
- Before every commit run the staged publication check. Before every push check all outgoing refs and their full reachable histories. `make setup` configures local hooks; CI independently validates public history.
- Do not store credentials, environment secrets, Python caches or generated demo runs in Git.

## Development and commits

Make focused commits with a single purpose. Separate simulator behavior, runner changes, review tools, tests, evidence and documentation when practical. Explain the concrete behavior and relevant validation in commit messages. Do not bundle unrelated changes.

Keep usage, service guarantees, data formats and limitations documented. Keep phase schedules and planning/review records local. Never represent AI annotations as independent human review or fixture replay as fresh inference. Keep hidden evaluator state out of model observations.

Run `make test` for behavior changes and `make validate` for changes affecting committed evidence or replay. Do not rerun paid live evaluation unless the task requires it. Preserve existing traces and append new runs with unique output paths.
