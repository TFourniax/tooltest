---
name: diffwitness
description: Require causal evidence for code changes made by coding agents. Use when implementing, fixing, refactoring, or reviewing code so a green test result is not treated as proof by itself.
---

# DiffWitness — proof-carrying code changes

Treat completion as a claim that must be supported by executable evidence.

## Core rule

Do not report a code-changing task as complete merely because tests are green. A useful regression command should distinguish the old behavior from the proposed behavior, and the real patch should be challenged counterfactually.

DiffWitness asks:

1. Does the candidate pass stably?
2. Do candidate regression tests fail against the captured pre-change state?
3. Which exact Git hunks are necessary under that evidence?
4. What smallest real-hunk subset is sufficient?
5. Are apparently removable hunks actually mutual backups?
6. Is any conclusion unstable or flaky?

## Preferred workflow

When the session is launched through `dw guard`, do normal implementation work. DiffWitness has already captured the pre-agent repository state and will run automatically when the agent exits.

Examples:

```bash
dw guard -- claude
dw guard -- codex
```

When a lifecycle hook armed DiffWitness automatically, continue working normally. If the Stop hook blocks completion, read its reason, improve the code/tests, and try to finish again. Do not bypass the proof merely to end the session.

When neither Guard nor lifecycle hooks are active, run this before declaring completion:

```bash
dw prove --base HEAD --candidate WORKTREE
```

`dw prove` auto-detects a conservative evidence command when the repository has an explicit test configuration/script. If detection is ambiguous, use:

```bash
dw doctor
```

and configure `.diffwitness.toml` or pass `--test` explicitly.

## Interpretation

- `WITNESSED`: removing that exact candidate hunk makes the selected evidence stably fail.
- `UNWITNESSED`: selected evidence remains stably green without that hunk. Investigate scope creep, redundancy, or missing evidence.
- `INCONCLUSIVE`: do not make a causal claim; patch application, timeout, or instability prevented it.
- `mutual-backup`: individually removable changes jointly carry evidence.
- `strong surplus candidate`: individually removable and absent from all minimal sufficient sets in an exhaustive search at the discovered order.

An unwitnessed hunk is a review signal, not an automatic deletion instruction. It may implement a requirement not exercised by the selected evidence.

## Agent behavior after rejection

If proof fails:

1. Inspect the failing or unwitnessed hunks.
2. Remove accidental/scope-creep changes when safe.
3. Add or strengthen requirement-relevant regression tests when the change is intentional but unproven.
4. Re-run the proof.
5. State remaining inconclusive evidence explicitly rather than claiming certainty.

Never weaken tests just to make DiffWitness accept a patch.

## Security and privacy

DiffWitness runs locally in disposable Git worktrees. It does not require a model API, hosted service, or source-code upload. The evidence command is repository-controlled code, so apply the same trust rules you would apply before running that repository's test suite.
