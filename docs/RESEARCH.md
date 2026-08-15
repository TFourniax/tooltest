# Research notes: why counterfactual patch evidence

Last updated: 2026-08-15.

This document records the public evidence that motivated DiffWitness. It is not a literature review and should not be read as a claim that passing tests are useless. The narrower claim is that **a positive test outcome and causal evidence about a particular patch are different things**.

## 1. Positive validation often does not discriminate the bug

Xu & Wu, *Validation Evidence in LLM Repair Agents: How Much of What Passes Actually Tests the Bug?* (arXiv:2607.28871, 2026) capture validation commands at their exact working-tree states and replay them on buggy, candidate, and gold-fix states. Across 3,730 validation events in 643 rollouts on 110 tasks, they report that **46.0% of positive comparable events carried no bug-discriminating information**.

Source: https://arxiv.org/abs/2607.28871

DiffWitness adopts the same broad counterfactual instinct, but applies it as a general-purpose developer tool around a real Git diff rather than as post-hoc repair-agent trajectory analysis.

## 2. Weak suites admit semantically wrong patches

Li et al., *Probe to Generate: Program Variant-Guided Test Augmentation for Repository-Level Repair Benchmarks* (arXiv:2604.01518, ASE 2026) generate semantically modified program variants and find that **77% of SWE-bench Verified instances admit at least one surviving variant** under the original tests. Strengthening the suites reduces measured resolved rates of top repair agents.

Source: https://arxiv.org/abs/2604.01518

This motivates treating “green” as one observation, not the end of the argument.

## 3. Changed-code coverage targets a different gap

Zhou et al., *Change And Cover: Last-Mile, Pull Request-Based Regression Test Augmentation* (arXiv:2601.10942, 2026) targets modified PR lines that remain uncovered and generates tests for them.

Source: https://arxiv.org/abs/2601.10942

ChaCo asks whether changed code is covered and helps generate tests. DiffWitness asks whether the selected evidence outcome changes when **the actual changed hunk is removed**, then searches which real hunk subsets are sufficient from the base.

The approaches are complementary: patch coverage can improve the candidate evidence command; DiffWitness can then ask whether that evidence actually witnesses the patch.

## 4. Agents can overfit the thing being checked

Ma, Kereopa-Yorke & Schultz, *Building to the Test: Coding Agents Deliver What You Check, Not What You Requested* (arXiv:2606.28430, 2026), use mechanical audits and no-op ablations alongside a hidden test oracle and show a setting where agents reach near-perfect oracle scores while failing the intended reusable-library requirement.

Source: https://www.microsoft.com/en-us/research/publication/building-to-the-test-coding-agents-deliver-what-you-check-not-what-you-requested/

DiffWitness cannot solve specification incompleteness. It deliberately reports its scope as “under the selected evidence command” and preserves that command in the certificate.

## 5. Flaky execution weakens causal interpretation

Ge & Zhang, *Understanding and Detecting Flaky Builds in GitHub Actions* (arXiv:2602.02307, 2026), study 1,960 open-source Java projects. Among rerun builds in their dataset, 67.73% exhibited flaky behavior, affecting 51.28% of projects studied.

Source: https://arxiv.org/abs/2602.02307

DiffWitness v0.2 therefore has repeated evidence runs as a first-class feature. Mixed pass/fail outcomes are `flaky` and yield an inconclusive causal claim.

## 6. Traceability remains a bottleneck

The 2026 ISSTA work *Understanding Automated Program Repair Agents Through the Lens of Traceability* analyzes repair-agent trajectories and reports that test generation and regression-test selection remain important bottlenecks, with agents often failing to reproduce issues or run relevant regression tests.

Source: https://research.ibm.com/publications/understanding-automated-program-repair-agents-through-the-lens-of-traceability-an-empirical-study

This is one reason DiffWitness is designed to emit a machine-readable, content-addressed evidence certificate rather than only terminal prose.

## 7. GitHub can surface evidence where review happens

GitHub Actions supports file- and line-specific `notice`, `warning`, and `error` workflow commands plus a job-summary file. DiffWitness v0.2 uses these native interfaces to put unwitnessed/inconclusive hunk signals directly into CI review surfaces without a paid SaaS backend.

Source: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands

## Design hypothesis

The useful unit of review for AI-heavy development is shifting from:

> “Did the test suite pass?”

toward:

> “What evidence distinguishes the old behavior from the new one, which exact edits carry that evidence, what smaller edit-set is sufficient, and is the observation stable?”

DiffWitness is an experiment in making that second question cheap enough to run in ordinary repositories.
