# DiffWitness Gate

`dw gate` is the CI / pull-request boundary of the DiffWitness proof layer.

Guard proves the before/after transaction produced by an interactive coding agent. Gate proves an already-existing Git diff. Both use the same evidence semantics.

## One command

```bash
dw gate --base origin/main --candidate HEAD
```

If the repository exposes a conventional test command, DiffWitness discovers it. Otherwise configure `.diffwitness.toml` or pass `--test`.

## Automatic proof strategy

The default strategy is `auto`:

```text
small production diff   -> exhaustive hunk proof
large production diff   -> Adaptive Core
```

The default switch occurs above 16 production mutations. It is configurable:

```bash
dw gate \
  --base origin/main \
  --candidate HEAD \
  --adaptive-threshold 24 \
  --adaptive-budget 60
```

### Exhaustive mode

```bash
dw gate --base origin/main --candidate HEAD --strategy exhaustive
```

Runs candidate/base contrast, individual real-hunk ablation, sufficient-subset search and interaction search under the configured budgets.

### Adaptive mode

```bash
dw gate --base origin/main --candidate HEAD --strategy adaptive
```

Adaptive Core starts from the real full patch, requires stable bug-discriminating base/candidate contrast, then removes groups of real mutations under a strict run budget. It finishes with a single-mutation cleanup pass.

A blocking policy only accepts an Adaptive Core result when the returned core is proven **1-minimal** under the selected evidence. That means removing any one remaining mutation loses the observed stable pass. It does **not** mean the core is globally minimum.

If the budget is exhausted before 1-minimality is established, the blocking result is inconclusive rather than optimistic.

## Policies

Evidence and policy are separate concepts.

### observe

```bash
dw gate --base origin/main --policy observe
```

Collect evidence without blocking on policy. This is the safest rollout mode for an existing repository.

### balanced

Default. Rejects unstable/inconclusive evidence and strong evidence-removable surplus, while avoiding the assumption that every intentional requirement must be individually witnessed by one command.

### strict

```bash
dw gate --base origin/main --policy strict
```

Best suited to narrow bug fixes with a strong regression test. Requires stable base-fail -> candidate-pass contrast and rejects unwitnessed/inconclusive production changes.

## Project configuration

```toml
[diffwitness]
test = "pytest -q"
prepare = "python -m pip install -e ."
timeout = 300
stability_runs = 2
policy = "balanced"
strategy = "auto"
adaptive_threshold = 16
adaptive_budget = 40
test_overlay = true
ignore = ["generated/**"]
share = []
```

Explicit CLI values override project configuration.

## GitHub Action

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- uses: TFourniax/tooltest@main
  with:
    base: ${{ github.event.pull_request.base.sha }}
    candidate: ${{ github.event.pull_request.head.sha }}
    policy: balanced
    strategy: auto
```

The action emits:

- file annotations for suspicious/removable evidence surfaces;
- a job summary;
- machine-readable outputs;
- JSON and Markdown evidence artifacts by default;
- `proof_mode` = `exhaustive`, `adaptive-core`, or `not-required`.

For production use, pin a stable release tag once public releases are cut rather than tracking `main` indefinitely.

## Documentation/test-only changes

DiffWitness does not force unrelated executable tests to become fake evidence for a documentation-only diff.

When no executable causal mutation remains after test/documentation/ignore filtering, Gate emits a formal content-addressed `dw0_...` certificate with:

```text
outcome = proof-not-required
```

This is not a waiver hidden as success. The certificate explicitly states that no test-based causal claim was made.

## Why Gate is not a review bot

A review bot generally asks a model or static analyzer whether code *looks* suspicious. Gate asks the repository to execute controlled counterfactual variants of the exact patch.

The two approaches can coexist. DiffWitness is intended to answer a different question: **what did the selected executable evidence actually discriminate about this change?**
