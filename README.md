# DiffWitness

**Tests passing is an outcome. DiffWitness asks whether the patch actually caused it.**

DiffWitness is a free, language-agnostic CLI and GitHub Action that builds **counterfactual evidence for a Git diff**. Instead of treating a green test command as proof that every change in a patch is justified, it reruns the same evidence against controlled variants of the *real patch*.

It answers four questions:

1. **Contrast** — do the candidate's tests fail on the old code and pass on the candidate?
2. **Necessity** — which exact Git hunks make the evidence fail when removed?
3. **Sufficiency** — what smallest set of real hunks is enough to turn the old code green?
4. **Interaction** — are apparently optional hunks secretly backing each other up?

With `--stability-runs N`, every claim must survive repeated execution, so a flaky pass/fail is reported as **inconclusive**, not causal evidence.

## Why

A normal CI result says:

```text
128 tests passed ✅
```

DiffWitness can say:

```text
BASE + candidate tests       STABLE FAIL
CANDIDATE                    STABLE PASS

WITNESSED     src/auth.py hunk 1/3
WITNESSED     src/auth.py hunk 2/3
UNWITNESSED   src/auth.py hunk 3/3

minimal sufficient set: {hunk 1, hunk 2}
strong surplus candidate: hunk 3
```

That is a different primitive from coverage. A line can be executed without being necessary to the observed result. It is also different from classic mutation testing: DiffWitness does not invent synthetic mutants for its core analysis; **the submitted patch itself is the mutation surface**.

## Install

Requires Python 3.11+ and Git.

```bash
pipx install .
```

During early development you can also clone the repository and run:

```bash
python -m pip install -e .
```

There are no runtime Python dependencies.

## Fast start

Inside a Git repository with local changes:

```bash
diffwitness prove \
  --base HEAD \
  --candidate WORKTREE \
  --test "pytest -q"
```

`WORKTREE` snapshots staged, unstaged and non-ignored untracked files without touching your real Git index.

For a branch/PR:

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "pytest -q" \
  --stability-runs 2 \
  --certificate diffwitness-evidence.json \
  --report diffwitness-evidence.md
```

## One-command project setup

```bash
diffwitness init --test "pytest -q"
```

This creates:

- `.diffwitness.toml` with sane evidence-search defaults;
- `.github/workflows/diffwitness.yml` for PR analysis.

Then ordinary use can be as short as:

```bash
diffwitness prove --base origin/main --candidate HEAD
```

Example config:

```toml
[diffwitness]
test = "pytest -q"
stability_runs = 2
sufficient_search = true
max_subset_order = 3
max_subset_runs = 32
interaction_search = true
max_interaction_runs = 20
```

## GitHub Action

After `actions/checkout` with full history:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: DiffWitness
  uses: TFourniax/tooltest@main
  with:
    base: ${{ github.event.pull_request.base.sha }}
    candidate: ${{ github.event.pull_request.head.sha }}
    stability-runs: 2
```

The Action automatically:

- annotates unwitnessed/inconclusive hunks on their changed file/line;
- writes a Markdown evidence certificate to the GitHub job summary;
- exposes `certificate_id`, `witness_ratio`, `minimal_sufficient_order`, and `surplus_candidate_hunks` as outputs.

To make the proof a hard gate:

```yaml
    strict: true
```

Strict mode requires stable base→candidate contrast and every analyzed hunk to be individually witnessed. Start non-strict if your evidence command is narrow, then ratchet once it represents the behavior you care about.

## The evidence model

### 1. Candidate-test overlay

If a patch adds a regression test, DiffWitness copies the **test change only** onto the base before running the evidence command:

```text
old production code + new test     FAIL
new production code + new test     PASS
```

This avoids the misleading comparison `old code without test` vs `new code with test`.

Use `--no-test-overlay` for projects where tests and production changes cannot be separated cleanly. Add custom test locations with `--test-glob`.

### 2. Necessity: reverse hunk ablation

For each production hunk `H`, DiffWitness starts from the candidate and reverse-applies that exact Git hunk:

```text
candidate - H → run evidence
```

- **WITNESSED** — evidence becomes stably failing; `H` is necessary under this command/environment.
- **UNWITNESSED** — evidence remains stably passing; the command does not currently justify `H`.
- **INCONCLUSIVE** — patch application, timeout, or unstable executions prevent a causal claim.

### 3. Sufficiency: build up from base

When the base is stably failing and candidate stably passing, DiffWitness can search small subsets of real production hunks:

```text
base + candidate tests + {H1}       FAIL
base + candidate tests + {H2}       FAIL
base + candidate tests + {H1,H2}    PASS
```

The first passing cardinality is a **minimal-cardinality sufficient evidence core** within the configured search space.

The search is intentionally budgeted:

```bash
--max-subset-order 3
--max-subset-runs 32
```

DiffWitness reports whether it exhaustively enumerated the cardinality at which a core was found. It only labels a hunk a **strong surplus candidate** when that search was exhaustive and the hunk is both individually removable and absent from every minimal sufficient set found.

### 4. Hidden redundancy: mutual backup

Two candidate hunks can each look unnecessary in isolation:

```text
candidate - H1         PASS
candidate - H2         PASS
candidate - H1 - H2    FAIL
```

DiffWitness reports this pair as **mutual backup** rather than pretending both hunks are independently useless. This is common when a patch introduces overlapping fallbacks or duplicate ways of satisfying the same test.

### 5. Stability before causality

```bash
--stability-runs 3
```

Each candidate/base/ablation/subset variant is executed repeatedly on the same isolated code state.

- all pass → `stable-pass`
- all fail → `stable-fail`
- mixed outcomes → `flaky`
- any timeout → `timeout`

A flaky or timed-out variant never becomes a witnessed/unwitnessed causal claim.

## Evidence certificates

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "pytest -q" \
  --certificate evidence.json \
  --report evidence.md
```

The JSON schema v2 contains:

- exact base/candidate SHAs;
- selected command and execution configuration;
- repeated-run outcomes;
- hunk locations and deltas;
- necessity results;
- sufficient subsets;
- mutual-backup pairs;
- minimization results;
- environment metadata;
- a content-addressed `dw2_...` certificate id.

Render it later:

```bash
diffwitness show evidence.json
```

The schema is documented in `schema/diffwitness-report-v2.schema.json`.

## Patch minimization

DiffWitness can additionally attempt a greedy local reduction:

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "pytest -q" \
  --stability-runs 2 \
  --minimize \
  --reduction-patch remove-surplus.patch
```

The algorithm only removes production hunks when the selected evidence stays stably green. This is a local/greedy reduction, not a proof of a globally smallest patch.

## Useful gates

Require a genuine regression contrast:

```bash
--require-contrast
```

Require every analyzed hunk to have an individual witness:

```bash
--require-all-witnessed
```

Reject strong surplus candidates discovered by exhaustive minimal-core search:

```bash
--require-no-surplus
```

These can be combined, but a broad “all hunks witnessed” policy is intentionally stricter than many teams will want for refactors or observability changes. The report is useful even when no gate is enabled.

## Large repositories / expensive test suites

Counterfactual evidence costs test executions. Control it deliberately:

- use the narrowest command that still represents the requirement;
- use `--prepare` for setup that must exist in isolated worktrees;
- use `--share node_modules` or another safe cache path to avoid reinstalling large dependencies;
- bound subset and interaction search;
- start with `--stability-runs 1` locally and use 2+ for CI evidence that matters.

`--share` is a performance escape hatch: tests can mutate the shared target. Do not share stateful application data unless cross-variant contamination is acceptable.

## Security model

DiffWitness executes the command you provide and may execute code from the base and candidate revisions. Treat untrusted PR code accordingly. See `SECURITY.md`.

## What DiffWitness does not claim

A witness is **relative to the selected evidence command and environment**. It does not prove the whole product requirement, security, performance, maintainability, or semantic correctness in general.

An unwitnessed hunk is not automatically wrong. It may be required by a different test, a non-test requirement, a deployment concern, or a behavior outside the selected command. DiffWitness is designed to turn “trust me, tests pass” into a reviewable evidence map — not to replace engineering judgment.

## Why this direction exists now

Recent work on coding-agent validation shows that a large fraction of positive validation events may carry no bug-discriminating information, while repository-level test suites can admit many semantically incorrect variants. DiffWitness operationalizes a practical response: replay evidence counterfactually against the actual patch and make uncertainty explicit.

See `docs/RESEARCH.md` and `docs/COMPETITIVE_CHECK.md` for sources, nearby work, and the deliberately narrow novelty statement.

## License

MIT.
