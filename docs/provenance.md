# Evidence and assistance provenance

Every empirical claim must identify its collection, version and denominator. Preserve attempted episodes, infrastructure failures, exclusions, resumed attempts and analyzed records separately. Provider model aliases do not establish fixed weights. Measured usage does not establish billed cost.

Each run should retain model/provider identifiers, request settings, policy and configuration hashes, context/world/rollout IDs, visible message history, tool calls and observations, stop reason, usage and latency when emitted. Evaluator-only state is stored separately and is never included in the model observation. A hash identifies bytes; it does not prove truthful execution.

Each annotation must identify its actual provenance: human, independent human, AI manual review, model judge or fixture-derived. Record reviewer identity/category, rubric version, trace hash, evidence references, uncertainty and adjudication. Do not promote AI review into human annotation. Model-judge agreement does not establish agreement with humans. Retain ungradable and missing reports with explicit counts.

Literature claims require a primary source with version, section and access scope; missing evidence is unverified. Research prose should distinguish a paper's reported finding from an independently reproduced result. State conflicting provenance statements together rather than selecting the more favorable one. Record source and data licenses independently.

AI assistance was used for the initial MVP code, explanations and AI manual trace review, and for the source audit, documentation and contract schema. The AI's inspection and automated checks are not independent research review or evidence of the user's understanding. Record actual human contributions and learning answers separately when supplied.

Code or content adaptation requires source URL, immutable revision where available, source/local paths, modification and license/notice record. Conceptual attribution alone is appropriate when no source or data is copied. Do not distribute private research inputs or local planning/review records. Fixture reproduction and offline reanalysis must be labeled as such; neither increases live sample counts.

See [evidence.md](evidence.md) for the existing collection's concrete provenance and [prior_art_diff.md](prior_art_diff.md) for inspected component overlap.
