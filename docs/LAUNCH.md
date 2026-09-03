# DiffWitness community launch

## Core message

> **Green is not proof.**
>
> DiffWitness independently interrogates the exact patch produced by Claude Code, Codex, another agent, or a human. It asks what the selected executable evidence actually distinguishes — and refuses to turn uncertainty into confidence.

Do not launch DiffWitness as “another AI code reviewer.” The differentiator is experimental counterfactual evidence over the **real Git diff**.

## 15-second explanation

Coding agents can write code and tests in the same trajectory. A green suite therefore does not automatically prove the patch fixed what it claims or that every extra edit is justified.

DiffWitness runs after generation. It replays candidate tests on the old code, removes real patch changes in controlled variants, detects redundant/surplus surface, classifies flaky evidence, and emits a content-bound certificate.

## Demo sequence

The first public demo should be terminal-first and reproducible:

```bash
pipx install diffwitness
cd any-git-repo
dw setup --agent claude   # or: codex
claude                    # or: codex
```

The provider runs normally. DiffWitness's native SessionStart and Stop hooks bind the exact
before/after Git change and run Proof, Debt, Understand and Continuity automatically. Codex
still requires its own project and hook trust review; DiffWitness never approves itself.

If native hooks are unavailable, the explicit process-boundary fallback remains:

```bash
dw guard -- claude
```

Then show a deliberately small bugfix where the agent also changes an unrelated second function.

Normal CI:

```text
128 passed
```

DiffWitness:

```text
causal contrast: proven
patch mutations: 2
retained causal core: 1
evidence-removable surface: 1
certificate: dw2_... / dwac1_...
```

Then edit one byte after proof and run:

```bash
dw verify evidence.json
```

Show:

```text
freshness: stale
verdict: INVALID
```

That is easier to understand than a feature list.

## ProofBench claim

Ship the repository with:

```bash
python benchmarks/proofbench.py
```

The benchmark pins four semantic cases:

- scope creep hidden behind a green candidate suite;
- new tests that also pass on the old code;
- behavior-preserving refactor;
- documentation-only change where no causal test claim should be fabricated.

The benchmark is a regression contract, not a marketing leaderboard.

## GitHub repository front page

Recommended public repository name:

```text
TFourniax/diffwitness
```

Recommended description:

> Independent executable proof for AI-generated code. Guard Claude Code/Codex, causally interrogate real Git patches, and carry verifiable evidence with the diff.

Suggested topics:

```text
ai-coding
coding-agents
claude-code
codex
testing
code-review
git
ci
software-verification
mutation-testing
```

## Launch post draft

### Hacker News / developer communities

**Title:** Show HN: DiffWitness – green tests are not proof for AI-generated patches

**Body:**

> Claude Code and Codex can now generate an implementation and its tests in the same trajectory. I wanted an independent layer that asks a harder question after generation: *what did those tests actually prove about the exact patch?*
>
> DiffWitness is open source and model-independent. It snapshots the repository before/after an agent, overlays candidate tests onto the old code, runs controlled counterfactual variants of the real Git diff, distinguishes repair evidence from preservation evidence, detects non-discriminating tests and surplus patch surface, and emits content-addressed certificates that become stale when the code changes.
>
> The low-friction path is one-time `dw setup`, then normal `claude` or `codex` use; the native Stop hook runs the verification boundary automatically. `dw guard -- <agent>` remains an explicit fallback, and CI uses `dw gate`.
>
> There is no hosted service and no model API key. The repository includes ProofBench so the key semantics are reproducible rather than screenshots.
>
> I would particularly value adversarial examples where DiffWitness is too strict or, more importantly, accepts evidence it should not.

## Community channels

Prioritize technical communities where contributors can reproduce and criticize the mechanism:

1. GitHub public release + Discussions/issues.
2. Hacker News Show HN.
3. Claude Code / Anthropic plugin community channels.
4. OpenAI developer community / Codex showcase channels.
5. Reddit communities centered on programming, testing, coding agents, and local developer tooling — only with a concrete reproducible demo.
6. X/LinkedIn after technical launch, linking to ProofBench rather than a vague product page.

Avoid mass posting identical copy everywhere. Early credibility is more valuable than reach.

## Launch success criteria

Do not optimize the first week for stars alone. Track qualitatively:

- independent reproductions of ProofBench;
- real repositories adding `dw gate` to CI;
- agent users completing normal Claude/Codex sessions through the native hooks without invoking `dw guard`;
- false-negative evidence reports converted into permanent benchmark fixtures;
- false-positive reports that improve policy/semantic routing;
- external integrations that consume the unified certificate schema.

## What not to claim

Never say:

- “DiffWitness proves the program correct.”
- “A witnessed hunk is universally necessary.”
- “Adaptive Core finds the globally smallest patch.”
- “Git worktrees are a security sandbox.”
- “A content-addressed certificate authenticates who created it.”

Say exactly what was established under the selected executable evidence and environment.

That restraint is part of the product.
