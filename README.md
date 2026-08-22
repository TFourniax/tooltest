# DiffWitness

> **Don't trust the agent. Don't trust the green check. Prove the change — and keep the debt it creates accountable.**

DiffWitness is a local-first **proof and debt-control layer for AI-generated code**.

Claude Code, Codex, humans and scripts can all produce convincing patches. DiffWitness sits *after generation* and asks two harder questions:

1. **What does the executable evidence actually prove about this exact Git diff?**
2. **What engineering obligations did this change leave behind, and how will we prove they were repaid?**

It does not ask one LLM to review another LLM. Its strongest claims come from controlled experiments on the **real Git patch**, then those claims can become replayable `DW-...` debt lineages instead of disappearing into a one-off CI log.

```text
                    Claude / Codex / human
                              |
                              v
                       changed repository
                              |
                 +------------+------------+
                 |                         |
                 v                         v
           DiffWitness Gate           Debt analysis
       contrast / necessity       causal + deterministic
      sufficiency / stability     + bounded heuristics
                 |                         |
                 +------------+------------+
                              |
                              v
                     proof certificate
                              +
                       Debt Ledger
                              |
                  repay -> gate -> recheck
                              |
                              v
                   verified resolution
```

## Why this exists

AI makes code generation cheap. Verification and maintenance do not become cheap automatically.

A normal CI result can tell you:

```text
128 tests passed
```

but not necessarily:

- whether the new test would have failed on the old implementation;
- which real hunks are necessary for the observed behavior;
- whether two apparently removable hunks secretly back one another up;
- whether the patch contains implementation surface not witnessed by the selected evidence;
- which future obligations were introduced by this agent session;
- whether a later cleanup genuinely repaid an obligation or merely made a warning disappear.

DiffWitness is built around one principle: **unknown evidence stays unknown**. It should fail closed or label a claim heuristic/inconclusive rather than manufacture certainty.

## Alpha status

Current version: **`0.4.0a1` — Proof + Debt Control Alpha**.

The alpha is intended for real repositories and real agent workflows, with conservative semantics. The project is not yet claiming a stable public API or universal debt model.

Core characteristics:

- Python 3.11+ and Git;
- zero Python runtime dependencies;
- local execution by default;
- no hosted DiffWitness account required;
- no model API required for proof or debt accounting;
- no source-code upload required by the core engine;
- Claude Code / Codex integration plus a generic process wrapper;
- GitHub Action support;
- append-only, hash-chained Debt Ledger with replayable lineages.

See [`CHANGELOG.md`](CHANGELOG.md) for the exact alpha boundary.

## Install

For the current repository build:

```bash
python -m pip install -e .
```

or:

```bash
pipx install .
```

Verify the install:

```bash
dw --version
dw doctor
```

Once the repository is public, a Git install can be used without cloning manually:

```bash
pipx install git+https://github.com/TFourniax/tooltest.git
```

For production/community distribution, prefer a tagged release or package-registry release over pinning workflows to `main`.

## The 60-second path

### 1. See what evidence DiffWitness would run

```bash
dw doctor
```

DiffWitness conservatively detects explicit repository signals for common Python, JavaScript/TypeScript, Rust, Go, JVM, PHP and Ruby projects. An explicit `.diffwitness.toml` always wins.

Example:

```toml
[diffwitness]
test = "pytest -q"
stability_runs = 2
sufficient_search = true
max_subset_order = 3
max_subset_runs = 32
interaction_search = true
max_interaction_runs = 20

[debt]
max_total = 100
max_per_change = 12

[debt.security]
max = 10
```

### 2. Launch your normal agent through the proof boundary

```bash
dw guard -- claude
```

or:

```bash
dw guard -- codex
```

Guard captures the repository before the agent starts, leaves the agent interactive, then evaluates the exact resulting repository state after the agent exits.

### 3. Inspect project debt

```bash
dw health
```

### 4. Pick a repayment mission

```bash
dw plan
```

Then either ask DiffWitness for the constrained prompt:

```bash
dw repay --prompt-only
```

or let it run the agent, gate the resulting patch, re-measure debt and replay the original debt claims:

```bash
dw repay -- claude
```

## Proof Guard

`dw guard` is the lowest-friction local workflow.

### Balanced — default

```bash
dw guard --policy balanced -- claude
```

Rejects unstable/inconclusive evidence and strong surplus candidates while allowing individually unwitnessed hunks that may represent requirements outside one narrow test command.

### Strict

```bash
dw guard --policy strict -- codex
```

Requires stable `base-fail -> candidate-pass` contrast and rejects any unwitnessed or inconclusive analyzed production hunk. It is especially useful for bug fixes where a new regression test should genuinely witness the repair.

### Observe

```bash
dw guard --policy observe -- claude
```

Does not block on proof policy. Use it to learn what an existing test suite actually demonstrates before enforcing a merge gate.

See [`docs/GUARD.md`](docs/GUARD.md) and [`docs/GATE.md`](docs/GATE.md).

## What “proof” means here

DiffWitness currently investigates five bounded dimensions.

### Contrast

When candidate tests changed, DiffWitness can carry the **test change only** back to the historical base:

```text
old production code + candidate regression tests    STABLE FAIL
candidate production code + same tests              STABLE PASS
```

That is materially stronger than observing both old and new CI runs independently.

### Necessity

For each analyzed real production mutation `H`:

```text
candidate - H  -> run the same evidence
```

The result is:

- **WITNESSED** — removing the exact mutation makes the evidence stably fail;
- **UNWITNESSED** — the evidence remains stably green without it;
- **INCONCLUSIVE** — application, timeout or instability prevents a causal claim.

An unwitnessed mutation is a review/debt signal, **not** an automatic deletion instruction.

### Sufficiency

DiffWitness can start from base + candidate tests and add subsets of the real production patch:

```text
base + tests + H1          FAIL
base + tests + H2          FAIL
base + tests + H1 + H2     PASS
```

Small patches can be searched exhaustively inside configured bounds. Large patches can use the budgeted Adaptive Core engine. Search budgets and completeness are recorded instead of being hidden.

### Interaction

Individual ablation can miss mutual backup:

```text
candidate - H1          PASS
candidate - H2          PASS
candidate - H1 - H2     FAIL
```

DiffWitness can surface the pair rather than calling both hunks simply useless.

### Stability

Variants are classified as:

```text
stable-pass
stable-fail
flaky
timeout
```

A flaky or timed-out experiment never becomes a witnessed/unwitnessed causal claim.

The semantic contract is documented in [`docs/PROOF_PROTOCOL.md`](docs/PROOF_PROTOCOL.md).

## Debt Ledger

Proof answers a question about one change. The Debt Ledger keeps the obligations discovered across changes alive.

A debt item has a stable `DW-...` identity and carries:

```text
category         evidence / test / security / architecture / ...
rule             why the obligation exists
measurement      causal / deterministic / historical / heuristic
points           accounting weight
path + line       when meaningful
introduced_by    Git / certificate / agent provenance
observed evidence
verification     how the claim can be replayed
status           open / resolved
accepted         acknowledged debt remains debt
history          append-only lifecycle
```

The aggregate score is intentionally **not** the product. The durable lineage plus replayable verification is.

### Measure one change

```bash
dw debt --base origin/main --candidate HEAD
```

With a DiffWitness certificate:

```bash
dw gate \
  --base origin/main \
  --candidate HEAD \
  --certificate evidence.json

dw debt \
  --base origin/main \
  --candidate HEAD \
  --certificate evidence.json
```

A certificate must pass integrity/content binding before debt accounting trusts it. Merely placing a JSON file at `--certificate` does not waive `unverified_change` debt.

### Project health

```bash
dw health
```

Health scans are executed against an immutable snapshot of the current worktree. The report is therefore bound to the tree that was actually inspected, including uncommitted source changes, rather than incorrectly claiming that dirty content was `HEAD`.

### Inspect an obligation

```bash
dw ledger list
dw ledger show DW-...
dw ledger history DW-...
```

### Accept deliberate debt

```bash
dw ledger accept DW-... \
  --reason "temporary provider migration; removal scheduled after cutover"
```

Acceptance is governance, not deletion. Accepted debt remains visible and counted by default.

### Recheck without an agent

```bash
dw recheck DW-...
```

or:

```bash
dw recheck --all
```

An item closes automatically only when its verification adapter establishes the required condition. Unsupported, unavailable or unstable replays remain open/inconclusive.

Full model: [`docs/DEBT_LEDGER.md`](docs/DEBT_LEDGER.md).

## Portable Debt Ledger

The default local ledger lives outside the candidate diff:

```text
.git/diffwitness/debt-ledger.jsonl
```

That is safe for local experimentation but ephemeral CI runners and new clones need a shared baseline. DiffWitness can checkpoint the same hash-chained event history on a dedicated Git ref without rewriting `HEAD`:

```text
refs/diffwitness/debt-ledger
```

Typical trusted workflow:

```bash
dw ledger pull
dw health
# or record accepted change debt with `dw debt ...`
dw ledger push
```

Useful diagnostics:

```bash
dw ledger status
dw ledger checkpoint
```

Safety properties:

- local writes use atomic replacement and an inter-process lock;
- stale processes re-read the latest history before state transitions;
- semantically impossible histories fail closed even if their hash chain is internally valid;
- remote updates are non-force fast-forwards;
- concurrent/divergent histories are never guessed together automatically;
- network/authentication failures cannot silently reset the cumulative baseline;
- a genuinely absent remote ref is treated as first use unless `--required` is requested.

The public PR action is intentionally **read-only** with respect to the shared ledger ref. Publish a new checkpoint only from a trusted post-merge/default-branch workflow or an explicit maintainer operation.

## GitHub Action

Example PR gate:

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

- runs the same public Gate semantics as local usage;
- annotates unwitnessed/inconclusive changed hunks;
- writes proof + debt information into the job summary;
- emits machine-readable proof/debt outputs;
- restores the cumulative Debt Ledger checkpoint by default before evaluating debt budgets;
- preserves JSON + Markdown evidence as an Actions artifact by default;
- **never pushes the shared Debt Ledger from a PR run**.

For a hard proof gate:

```yaml
with:
  strict: true
```

For a repository that has not initialized a portable ledger ref yet, the Action starts from an empty baseline. Use `ledger-sync: false` only when cumulative debt is intentionally out of scope.

## Proof certificates

```bash
dw prove \
  --base origin/main \
  --candidate HEAD \
  --certificate evidence.json \
  --report evidence.md
```

Certificates bind claims to concrete Git content and record evidence command/configuration, repeated outcomes, mutation locations, necessity/sufficiency results, interaction results, search budgets, environment metadata and a content-addressed identifier.

Verify integrity/freshness:

```bash
dw verify evidence.json --against HEAD
```

The report schema lives at [`schema/diffwitness-report-v2.schema.json`](schema/diffwitness-report-v2.schema.json).

## Claude Code + Codex

This repository ships native integration surfaces for both ecosystems:

```text
.claude-plugin/
.codex-plugin/
skills/diffwitness/SKILL.md
hooks/
```

The native hooks make the workflow convenient, but the process wrapper remains the reference trust boundary:

```bash
dw guard -- claude
dw guard -- codex
```

because DiffWitness then owns the before/after boundary rather than delegating it to a particular agent runtime.

## Security model

DiffWitness executes repository-controlled test/setup commands. Treat those commands with the same trust you would require before running that repository's own test suite.

Disposable Git worktrees isolate code variants from the active checkout. `--share` deliberately links selected paths such as dependency caches and therefore weakens isolation for those paths.

The Debt Ledger hash chain detects accidental/silent history mutation; it is **not** an external cryptographic signature proving that a malicious repository owner did not rewrite the ledger.

Core analysis does not require code to leave the machine.

See [`SECURITY.md`](SECURITY.md).

## What DiffWitness does not claim

DiffWitness is not a mathematical proof that software is correct.

It cannot establish requirements absent from the selected executable evidence. A weak test suite still produces weak evidence. External services can be nondeterministic. Environment differences matter. Security properties can require dedicated analysis.

Debt points are not:

- bug probabilities;
- percentages of code quality;
- engineering-hour estimates;
- confidence probabilities;
- CVSS or another security-severity standard.

The intended claim is narrower and useful:

> **Make it substantially harder for a green check — human or AI-generated — to masquerade as evidence it never provided, and make the remaining obligations difficult to silently forget.**

## Development

Run the local suite:

```bash
python -m unittest discover -s tests -v
python benchmarks/proofbench.py
```

Build distributions:

```bash
python -m pip install --upgrade build
python -m build
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT.
