# Related work and source boundaries

Audit date: 23 November 2026. This is a bounded source inspection, not an independent reproduction or a comprehensive novelty search. Repository revisions below were resolved through GitHub's public API; selected source, license and documentation files were read without running upstream code. Preprint versions and repository releases are distinct artifacts.

## Failure-Transparent Agents (FTA)

Zhu et al., [arXiv:2609.35732v1](https://arxiv.org/abs/2609.35732v1), §§2–5, fixes failed observations before eliciting final reports. This supports attribution of blocked-task reporting evaluation and the four fields `STATUS`, `EVIDENCE`, `LIMITATION`, `NEXT_ACTION`.

Repository [revision 0cb798d4aa78f123b5c7b1b2b26684e776d90301](https://github.com/junru-zhu/failure-transparent-agents/tree/0cb798d4aa78f123b5c7b1b2b26684e776d90301) describes v0.3.0. Inspected: `simulator.py`, `prompting.py`, annotation guide, judge report, six-model extension report, `paper/main.tex`, README and LICENSE. `FailedToolSimulator.invoke` returns the frozen observation; prompt construction excludes evaluator-only evidence requirements.

**Unresolved provenance discrepancy:** the arXiv abstract/methods describe 3,600 human-annotated responses; the pinned repository README and manuscript explicitly describe model-judge measurements without human validation. The judge report concerns 1,800 original responses; the extension is separate. Neither a human annotation guide nor agreement between model judges establishes completed independent human annotation. Retain the discrepancy; do not present headline rates as independently human-validated or combine cohorts without matched definitions. Code/data/documentation license: MIT, per LICENSE and README. No code or data imported here.

## LIMBO

Li, [arXiv:2609.29095v1](https://arxiv.org/abs/2609.29095v1), §§3–7 and Appendix A, studies stateful recovery and distinguishes faults that immediate read-back resolves from pending or redelivered writes. Proposition 1's verification-only limitation depends on a non-idempotent write and unbounded late execution; Proposition 2 assumes enforced deduplication and progress. Neither proves that any API accepting a string key is safe.

Repository [revision 2db09fba22a0572a70639162a808906409f612a8](https://github.com/jaxblack/limbo-bench/tree/2db09fba22a0572a70639162a808906409f612a8), README identifies release 1.0. Inspected `world.py`, `services.py`, `grader.py`, `behavior.py`, README and licenses. `World.settle` advances deferred work; `grade` distinguishes executed from live duplicates, including compensation. These support attribution of temporal ledgers, settlement and separate outcome measures. No upstream tests, model runs or headline rates were reproduced. Software: MIT; episode data and generated tables/figures: CC BY 4.0 under DATA_LICENSE, with third-party style exclusions. No code or data imported here.

## RetryBench

Liu, Liu and Lu, [arXiv:2610.15884v4](https://arxiv.org/abs/2610.15884v4), §§3, 6–7 and Appendices A–D, separates retry permission, settled effects and recovery. A lucky outcome cannot establish decision admissibility. The paper reports bounded wording/order studies, not production prevalence. Its abstract and HTML title differ; cite the version identifier to avoid ambiguity.

Repository [revision 4d59a728791bd5c52809080563f07b02ef128537](https://github.com/LIUYOU2015/retrybench/tree/4d59a728791bd5c52809080563f07b02ef128537) has package metadata 0.2.0 while README advertises PyPI 0.3.0. Inspected `scoring.py`, `service.py`, provisional retry-admissibility contract, README, package metadata and LICENSE. `retry_is_permitted` tests terminal authoritative nonexecution; stable-key protection is a separate service path. `score_exact_state` checks operation, task, tool, target and payload identity. Do not mistake the narrow helper for the entire paper predicate. License: PolyForm Noncommercial 1.0.0, not MIT; paper licensing is separate. No code, prompts, datasets or archive imported into the application; no reproduction claimed.

## Did It Happen? / ambiguous-tool-outcomes-benchmark

Sun's [repository revision 4b626e7cde61ec9275a30e23982d146ee6f4e65d](https://github.com/shushuyang231/ambiguous-tool-outcomes-benchmark/tree/4b626e7cde61ec9275a30e23982d146ee6f4e65d) currently identifies protocol `ambiguous-se-outcomes-v1.4`. Inspected README, citation metadata, `counterfactual_engine.py`, package metadata, LICENSE and LICENSE-DATA.md. The current repository is not assumed identical to its earlier 0.1.0 citation.

`run_counterfactual_pair` verifies identical initial timeout observations, groups worlds by message history, makes one model request per group, and applies its reply to each member. World groups can split after different observations. Its final outputs retain final claims/status and state outcomes. This establishes substantial overlap with paired recovery and reporting records; it does not establish that a full natural-language epistemic support audit is present or absent across the entire repository. Software: MIT; original research data/documentation/figures: CC BY 4.0 with exclusions. No source or data reused in application artifacts.

## ToolStorm

[Revision 30b4e219ffdd45636026a490d9f5b2b391c721d6](https://github.com/shi1720/toolstorm/tree/30b4e219ffdd45636026a490d9f5b2b391c721d6) describes beta 0.2.0. Inspected engine, contracts, replay, architecture/replay documentation, README, package metadata and MIT license. It wraps Python functions, records explicitly instrumented effects, and offers strict cassette replay and behavioral checks. `Contract.no_duplicate_effects` counts committed identities; replay rejects mismatches and unused calls and does not call the decorated live function. Replay is not a process sandbox, fresh model inference or independent evidence of truthful source logs. Synthetic timeout injection does not cancel a hung function. The bundled comparison is scripted, not an LLM performance study. Attribution is required for adapted source; none imported here.

## Evaluation framework

[Inspect's official documentation](https://inspect.aisi.org.uk/) describes tasks composed of datasets, solvers and scorers, plus tool execution and logs. Only the overview was inspected; no package version or license audit was performed, and nivakyo does not currently depend on Inspect. Framework availability alone validates neither claim extraction nor research design.

## Interpretation

These sources establish prior work on reporting, ambiguous effects, contracts, replay and interface sensitivity. They do not justify an exclusive “first benchmark” claim. Nivakyo's existing evidence remains the small synthetic development collection documented in [evidence.md](evidence.md). No source audit converts AI labels into human annotations or supplies new empirical results.
