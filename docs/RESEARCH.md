# Research notes — why DiffWitness exists

Research snapshot: **2026-08-15**.

This document records the product-discovery sweep behind DiffWitness. The objective was not to find a fashionable AI wrapper; it was to find a repeated pain, reject ideas already served by free tools, and implement a missing primitive.

## 1. Repeated pain: “green” validation is weaker than developers think

The strongest recent signal came from software-repair research.

**Xu & Wu, “Validation Evidence in LLM Repair Agents: How Much of What Passes Actually Tests the Bug?” (2026-07-30)** studies 3,730 validation events in 643 repair-agent rollouts on 110 tasks. The authors report that **46.0% of positive comparable validation events carry no bug-discriminating information**, and that 23.8% of baseline rollouts can close with an entire positive evidence base of this kind.

Primary source: <https://arxiv.org/abs/2607.28871>

This is broader than “agents sometimes lie.” Even when a test *really ran and really passed*, the evidence can still be logically irrelevant to the claimed repair.

A second 2026 study, **STING**, finds that weak regression suites can admit semantically wrong patches in SWE-bench-style evaluation; strengthening tests lowers top-agent resolved rates by 4.2–9.0 percentage points.

Primary source: <https://arxiv.org/abs/2604.01518>

## 2. We rejected the obvious implementation

The first idea was simply:

> Run the same regression test on the base and the candidate; require base-fail / candidate-pass.

That is useful, but it already exists.

### Existing global patch proof

`@jayadityavetsa/patchproof` explicitly promises to “prove that changed regression tests distinguish a patch from its base revision.” It was published before this project.

Package information: <https://socket.dev/npm/package/@jayadityavetsa/patchproof/overview/0.1.0-alpha.1>

AdaptOrch CEK likewise treats base-fail / patch-pass as strong evidence in an execution-backed patch verification system.

Source: <https://adaptorch.com/>

So DiffWitness does **not** stop at global patch contrast.

## 3. The missing question: which edits are actually witnessed?

Suppose a candidate has five hunks and the regression test does this:

```text
base      → FAIL
candidate → PASS
```

That proves something important about the patch as a whole. It still does not tell a reviewer whether:

- all five hunks are needed,
- one hunk fixes the issue and four are opportunistic refactors,
- two hunks are alternative/redundant implementations,
- or one behavior change simply has no test evidence.

DiffWitness therefore creates **counterfactual candidate states**:

```text
candidate - hunk A
candidate - hunk B
candidate - hunk C
...
```

The chosen tests are replayed on each state. This produces a **change-necessity / witness map** over the actual patch.

That is a different question from conventional coverage.

## 4. Why line/patch coverage is adjacent, not equivalent

**ChaCo — Change And Cover (2026)** targets PR-modified lines that are not exercised and uses an LLM to generate tests. It is explicitly designed to close a last-mile *patch coverage* gap.

Primary source: <https://arxiv.org/abs/2601.10942>

DiffWitness can complement this, but the metrics are different:

- Coverage: “was the changed code executed?”
- DiffWitness: “does the selected evidence stop being green if this proposed change is absent?”

A line can be executed without its changed behavior being necessary to the assertion. Conversely, a structural hunk can be necessary for compilation before line coverage is meaningful.

## 5. Why mutation testing is adjacent, not equivalent

Mutation testing deliberately injects synthetic faults into the program and measures whether tests kill those mutants. It is a powerful way to measure test-suite strength.

DiffWitness does not synthesize arbitrary mutants. Its counterfactuals are derived from the **actual candidate diff**. The unit of inquiry is review evidence:

> “If this exact proposed edit were not present, would the evidence still be green?”

That makes the output directly actionable during AI-assisted review.

## 6. Other product directions rejected during discovery

### Cross-LLM portable memory / handoff

Pain is real: users repeatedly complain about re-explaining context when moving between ChatGPT, Claude, coding agents, and other tools. But the space now contains Mem0-style shared memory, handoff CLIs, session-history aggregators, context versioning, and several “Git for context” projects. A new generic memory layer would be a crowded copy.

### Agent safety / command guards

Real incidents include coding agents deleting unrelated files, over-broad staging, and permission/scope failures. But 2026 already has multiple runtime guards, policy layers, sandbox products, task-scoped capability research, and repository-scope monitors. Building another allow/deny wrapper would not satisfy the novelty bar.

### Change budgets / task leases

The concept is valuable, but it is no longer empty territory. Anthropic exposes granular file/tool permissions; “change budget” prompts are documented in the community; task-scoped capability systems such as PORTICO have appeared in research; practical guard tools increasingly implement scoped write policies.

### Local CI debugger

Developers explicitly ask for a CI environment they can step through locally. New tools such as PipeStep and ActDebug already target that workflow.

### Environment fingerprint / “works on my machine” diff

Repeated pain, but many current tools already snapshot and compare OS/runtime/package/environment state, including several new 2026 packages.

### Physical sticky-note board → digital board

A compelling human problem, but Post-it App, Pocket.Vision, BoardScan and other products already capture or synchronize physical boards.

The selection process matters: most good-sounding “new” tools stop being new after twenty minutes of competitor research.

## 7. Current novelty claim, carefully stated

We searched for combinations of:

- Git hunk ablation,
- patch-hunk necessity,
- counterfactual test evidence,
- base/candidate test replay,
- patch coverage,
- mutation testing over diffs,
- and free/open-source patch proof tools.

As of **2026-08-15**, the sweep did not surface a general-purpose free tool that combines:

1. a snapshot of committed or dirty/untracked candidate state without rewriting the user's index,
2. candidate-side regression-test overlay onto the base,
3. base/candidate contrast,
4. automatic per-production-hunk reverse ablation,
5. a hunk→test-witness map,
6. optional greedy removal of surplus candidate edits.

This should be read as an evidence-based product-positioning statement, not an assertion that no unpublished/private implementation exists.

## 8. Design principle

DiffWitness intentionally avoids an AI dependency.

The interesting part of the product is not another model judgment; it is converting “tests passed” into reproducible execution evidence. The core should stay deterministic, local, cheap, and scriptable. An optional LLM can always explain a report later, but the proof primitive should not depend on one.
