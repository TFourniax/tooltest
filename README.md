# DiffWitness

> **Don't trust the agent. Don't trust the green check. Prove the change.**

DiffWitness is an open-source **proof layer for code changes**.

Claude Code, Codex, humans and scripts can all produce convincing patches. DiffWitness sits *after generation* and asks a different question:

> **What does the executable evidence actually prove about this exact Git diff?**

It does not ask an LLM to review another LLM. It performs controlled counterfactual experiments on the **real patch**.

```text
                     any coding agent
                  Claude / Codex / human
                           |
                           v
                  +------------------+
                  |   changed repo   |
                  +------------------+
                           |
                           v
                  +------------------+
                  |   DiffWitness    |
                  |    Proof Guard   |
                  +------------------+
                     /      |       \
                    /       |        \
             contrast   necessity   sufficiency
                  |         |           |
                  +---------+-----------+
                            |
                            v
                    proof certificate
```

## The zero-friction path

Install DiffWitness, then launch your normal agent through Guard:

```bash
dw guard -- claude
```

or:

```bash
dw guard -- codex
```

That is the workflow.

Guard captures the repository state **before** the coding agent starts, leaves the agent fully interactive, then proves the exact repository change after the agent exits.

No hosted DiffWitness account. No model API. No source-code upload. No second AI reviewer required.

## What "prove" means here

A normal CI result says:

```text
128 tests passed
```

DiffWitness can establish a much richer, explicitly bounded statement:

```text
BASE + candidate regression tests       STABLE FAIL
CANDIDATE                               STABLE PASS

WITNESSED      src/auth.py hunk 1/3
WITNESSED      src/auth.py hunk 2/3
UNWITNESSED    src/auth.py hunk 3/3

minimal sufficient core: {hunk 1, hunk 2}
strong surplus candidate: hunk 3
certificate: dw2_...
```

The tool currently investigates five dimensions:

1. **Contrast** — do the candidate's tests fail against the captured pre-change code and pass on the candidate?
2. **Necessity** — which exact real Git hunks make the evidence fail when removed?
3. **Sufficiency** — what smallest tested set of real hunks is enough to turn the old code green?
4. **Interaction** — do apparently removable hunks secretly back one another up?
5. **Stability** — does the conclusion survive repeated execution, or is it flaky/timeout/inconclusive?

This is deliberately different from coverage and from classic mutation testing. Coverage asks whether code executed. Mutation testing usually invents synthetic mutants. DiffWitness's core mutation surface is **the patch that is actually about to be trusted**.

## Proof Guard

### Balanced policy — default

```bash
dw guard --policy balanced -- claude
```

Rejects unstable/inconclusive evidence and strong surplus candidates while allowing individually unwitnessed hunks that may represent requirements outside one narrow test command.

### Strict policy

```bash
dw guard --policy strict -- codex
```

Requires stable `base-fail -> candidate-pass` contrast and rejects any unwitnessed or inconclusive analyzed production hunk.

This is especially useful for bug fixes where a new regression test should genuinely witness the repair.

### Observe policy

```bash
dw guard --policy observe -- claude
```

Never blocks on evidence policy. Use it to understand what an existing test suite truly demonstrates before turning DiffWitness into a merge gate.

See [`docs/GUARD.md`](docs/GUARD.md).

## Zero-config evidence discovery

Ask DiffWitness what it would run:

```bash
dw doctor
```

It conservatively detects explicit repository signals such as:

- npm / pnpm / yarn / bun test scripts;
- pytest configuration;
- Python `unittest` test directories;
- Cargo;
- Go modules;
- Maven;
- Gradle;
- Composer;
- RSpec.

Then this can be enough:

```bash
dw prove --base origin/main --candidate HEAD
```

Explicit configuration wins when a repository has a better targeted command:

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

The advanced CLI remains available as `diffwitness`.

## Candidate-test overlay

When an agent adds a regression test together with the fix, DiffWitness carries the **test change only** back to the captured base before evaluating contrast:

```text
old production code + new regression test      FAIL
new production code + same regression test     PASS
```

It does not confuse:

```text
old code without the new test      PASS
new code with the new test         PASS
```

with meaningful evidence.

## Real-hunk necessity

For each production hunk `H`:

```text
candidate - H  -> run the same evidence
```

Results are conservative:

- **WITNESSED** — removing this exact hunk makes the evidence stably fail;
- **UNWITNESSED** — evidence remains stably green without it;
- **INCONCLUSIVE** — application, timeout or instability prevents a causal claim.

An unwitnessed hunk is a review signal, **not** an automatic deletion instruction.

## Minimal sufficient cores

DiffWitness can also reason in the opposite direction: begin from the old code plus the candidate's regression tests and add small subsets of real production hunks.

```text
base + tests + H1          FAIL
base + tests + H2          FAIL
base + tests + H1 + H2     PASS
```

That produces a tested **minimal-cardinality sufficient evidence core** inside the configured search space.

Every combinatorial search carries an explicit budget and reports whether the relevant frontier was exhaustively evaluated. DiffWitness never converts budget exhaustion into fake certainty.

## Hidden redundancy / mutual backup

Individual ablation can lie by omission:

```text
candidate - H1          PASS
candidate - H2          PASS
candidate - H1 - H2     FAIL
```

H1 and H2 are not simply "both useless". They are redundant ways of carrying the same evidence. DiffWitness reports the pair as **mutual backup**.

## Stability before causality

```bash
dw prove \
  --base origin/main \
  --candidate HEAD \
  --stability-runs 3
```

Variants are classified as:

```text
stable-pass
stable-fail
flaky
timeout
```

A flaky or timed-out experiment never becomes a witnessed/unwitnessed causal claim.

## GitHub Action

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: DiffWitness
  uses: TFourniax/tooltest@main
  with:
    base: ${{ github.event.pull_request.base.sha }}
    candidate: ${{ github.event.pull_request.head.sha }}
```

When the repository exposes a conventional evidence command, the Action can auto-detect it. Otherwise pass `test:` or commit `.diffwitness.toml`.

The Action:

- annotates unwitnessed/inconclusive hunks on changed files;
- writes the evidence report into the job summary;
- emits machine-readable outputs;
- preserves JSON + Markdown proof certificates as an Actions artifact by default.

For a hard gate:

```yaml
    strict: true
```

## Claude Code + Codex plugins

This repository ships native plugin surfaces for both ecosystems:

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
.codex-plugin/plugin.json
skills/diffwitness/SKILL.md
hooks/
```

The lifecycle integration captures the pre-agent state at `SessionStart` and checks the produced patch at `Stop`. When proof is rejected, the hook can return the reason to the agent so it can improve the code/tests before completion.

The process wrapper remains the reference path:

```bash
dw guard -- claude
dw guard -- codex
```

because the proof boundary then belongs to DiffWitness rather than to a particular agent runtime.

## Evidence certificates

```bash
dw prove \
  --base origin/main \
  --candidate HEAD \
  --certificate evidence.json \
  --report evidence.md
```

Certificates record, among other things:

- exact base and candidate SHAs;
- evidence command and configuration;
- candidate/base repeated-run outcomes;
- hunk locations and deltas;
- necessity results;
- sufficient subsets;
- mutual-backup interactions;
- search budgets and exhaustivity;
- minimization results;
- environment metadata;
- a content-addressed certificate identifier.

Render one later:

```bash
diffwitness show evidence.json
```

The current JSON schema lives at [`schema/diffwitness-report-v2.schema.json`](schema/diffwitness-report-v2.schema.json).

The semantic contract is described in [`docs/PROOF_PROTOCOL.md`](docs/PROOF_PROTOCOL.md).

## Patch minimization

DiffWitness can greedily find a smaller passing candidate without touching your working tree:

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "pytest -q" \
  --minimize \
  --reduction-patch remove-surplus.patch
```

The reduction is a proposal, never an automatic rewrite.

## Install for development

Requires Python 3.11+ and Git.

```bash
python -m pip install -e .
```

or:

```bash
pipx install .
```

There are no Python runtime dependencies.

Once this repository is public, a Git install can be used without cloning manually:

```bash
pipx install git+https://github.com/TFourniax/tooltest.git
```

A packaged registry release and stable Action tag should be preferred for community distribution rather than pinning production workflows to `main`.

## Security model

DiffWitness executes repository-controlled test/setup commands. Treat those commands with exactly the same trust you would apply before running that repository's test suite.

Disposable Git worktrees isolate code variants from the active checkout, but `--share` can deliberately link caches/dependencies and therefore weakens isolation for those paths.

DiffWitness does not require code to leave the machine for its core analysis.

See [`SECURITY.md`](SECURITY.md).

## What DiffWitness does **not** claim

DiffWitness is not a mathematical proof that software is correct.

It cannot establish requirements absent from the executable evidence. A weak test suite can still produce weak evidence. External services can be nondeterministic. Environment differences matter. Security properties may require dedicated analysis.

The goal is narrower and useful:

> **Make it substantially harder for a green check — human or AI-generated — to masquerade as evidence it never actually provided.**

## Why this project exists now

Coding has become dramatically cheaper to produce. Verification has not become proportionally cheaper.

As coding agents increase change volume, the bottleneck moves from **writing code** to **deciding what deserves trust**.

DiffWitness is an attempt to make proof-carrying diffs a normal part of that new software-development stack.

## Status

DiffWitness is experimental software under active development. The causal semantics are intentionally conservative; unknown/incomplete evidence should stay visible rather than being converted into a confidence score.

Current release line: **0.3.x — Proof Guard / agent integration**.

## License

MIT.
