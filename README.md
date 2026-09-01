# DiffWitness

> **Don't trust the agent. Don't trust the green check. Prove the change — and keep the debt it creates accountable.**

DiffWitness is a local-first **runtime protection, proof and debt-control layer for AI-generated code**.

Claude Code, Codex, humans, scripts and other harnesses can all produce convincing patches. DiffWitness separates four jobs that are easy to blur together:

1. **PROTECT — optional:** should a supported agent action be blocked, observed or confirmed while the agent works?
2. **PROVE:** what does executable evidence actually establish about this exact Git diff?
3. **OWE:** what engineering obligations did the change leave behind, and how will we prove they were repaid?
4. **UNDERSTAND:** how should those bounded signals be explained to a human without upgrading uncertainty into fact?

It does not ask one LLM to review another LLM. Its strongest claims come from controlled experiments on the **real Git patch**. Runtime Protect observations remain `OBSERVED`; only the independent proof boundary can mint bounded proof claims.

```text
                    Claude / Codex / other agent
                              |
                   optional Protect layer
                  builtin / external / off
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

Likewise, a runtime harness can tell you that an agent attempted a dangerous command, but that still does not prove the final software works.

DiffWitness is built around one principle: **unknown evidence stays unknown**. It should fail closed or label a claim observed/heuristic/inconclusive rather than manufacture certainty.

## Alpha status

Current version: **`0.4.0a1` — Proof + Debt Control Alpha**.

The alpha is intended for real repositories and real agent workflows, with conservative semantics. The project is not yet claiming a stable public API, universal agent safety model or universal debt model.

Core characteristics:

- Python 3.11+ and Git;
- zero Python runtime dependencies;
- local execution by default;
- no hosted DiffWitness account required;
- no model API required for Protect, proof or debt accounting;
- no source-code upload required by the core engine;
- optional builtin Claude Code / Codex runtime Protect hooks;
- external-harness delegation and a true `off` mode;
- Claude Code / Codex native integration plus a generic process wrapper;
- GitHub Action support;
- append-only, hash-chained Debt Ledger with replayable lineages;
- bounded Portal projection that keeps Protect observations separate from Proof assurance.

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

## The fast path

### 1. Inspect evidence and local integration

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

### 2. Choose live runtime protection — optional

Inspect the environment:

```bash
dw protect detect
```

Use builtin DiffWitness guards:

```bash
dw protect enable
```

For current Codex builds, installing the hook file is only the first step: Codex itself must have its `hooks` feature enabled, the repository must pass Codex's normal project-trust flow, and the DiffWitness hooks must be approved through Codex's own hook-trust UI. DiffWitness never grants itself that trust. `dw protect status` stays conservative until a live Codex hook has actually invoked Protect. See [`docs/PROTECT.md`](docs/PROTECT.md).

Keep an existing external harness:

```bash
dw protect use external
```

Or use no DiffWitness live interception:

```bash
dw protect disable
```

All three paths keep the same Proof, Debt Ledger, Continuity and IdleProof semantics. `off` means no DiffWitness Protect interception hook is installed.

### 3. Launch your normal agent through the proof boundary

```bash
dw guard -- claude
```

or:

```bash
dw guard -- codex
```

Guard captures the repository before the agent starts, leaves the agent interactive, then evaluates the exact resulting repository state after the agent exits.

### 4. Inspect project state and debt

```bash
dw status
dw health
```

### 5. Pick a repayment mission

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

See [`docs/60_SECONDS.md`](docs/60_SECONDS.md).

## Protect — optional runtime safety

Protect is deliberately not mandatory and deliberately not the proof engine.

```text
builtin   DiffWitness installs supported live runtime hooks
external  another harness owns live runtime protection
off       no DiffWitness live interception
```

Builtin Protect currently supports Claude Code and Codex hook surfaces. Current Codex hooks are provider-feature/trust gated: DiffWitness can install its hook configuration, but it never enables project trust or approves its own hooks. Until a live trusted Codex hook reaches DiffWitness, the Codex adapter is reported conservatively rather than pretending runtime protection is active.

Protect starts with a bounded deterministic rule set for high-confidence cases such as destructive Git/filesystem operations, remote pipe-to-shell execution, writes outside the repository, direct `.git` writes, several credential/private-key patterns, destructive database/schema commands, dependency-install observation/confirmation, and lightweight post-edit JSON/Python syntax checks.

Policies:

```bash
dw protect enable --policy observe
dw protect enable --policy standard
dw protect enable --policy strict
```

- `observe` records findings without blocking;
- `standard` blocks high-confidence dangerous actions;
- `strict` additionally asks for confirmation on dependency installation where the provider hook protocol supports it; current Codex `PreToolUse` does not safely support `ask`, so Protect blocks that dependency-install action instead.

Clean actions are **not force-allowed by DiffWitness**. Protect stays silent and the provider's native permission system remains authoritative.

Inspect state and bounded local receipts:

```bash
dw protect status
dw protect log
```

Protect receipts intentionally exclude raw commands, source contents, raw prompts, raw agent-event streams and raw session identifiers. A provider's first live hook may add one bounded `active` receipt so readiness can mean "the hook actually ran" without inventing a risk finding. Portal receives only aggregate mode/health/policy and decision counts when sync is configured.

Full contract: [`docs/PROTECT.md`](docs/PROTECT.md).

## Proof Guard

`dw guard` is the stable before/after proof workflow and works independently of Protect mode.

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

Protect policy and Guard proof policy are separate controls even when they use similar words.

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

A debt item has a stable `DW-...` identity and carries category, rule, measurement provenance, points, location, introduction provenance, observed evidence, replay/verification semantics, lifecycle status and append-only history.

The aggregate score is intentionally **not** the product. The durable lineage plus replayable verification is.

Measure one change:

```bash
dw debt --base origin/main --candidate HEAD
```

Project health:

```bash
dw health
```

Inspect and govern obligations:

```bash
dw ledger list
dw ledger show DW-...
dw ledger history DW-...
dw ledger accept DW-... --reason "temporary migration debt"
dw recheck DW-...
```

Acceptance is governance, not deletion. An item closes automatically only when its verification adapter establishes the required condition.

Full model: [`docs/DEBT_LEDGER.md`](docs/DEBT_LEDGER.md).

## Portable Debt Ledger

The default local ledger lives outside the candidate diff:

```text
.git/diffwitness/debt-ledger.jsonl
```

For ephemeral CI runners and fresh clones, the same hash-chained history can be checkpointed on:

```text
refs/diffwitness/debt-ledger
```

Typical trusted workflow:

```bash
dw ledger pull
dw health
dw ledger push
```

Remote updates are non-force fast-forwards and divergent histories are never guessed together automatically.

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

The Action runs the same public Gate semantics as local usage, annotates relevant findings, emits machine-readable proof/debt outputs, restores the cumulative Debt Ledger baseline by default, preserves evidence artifacts, and **never pushes the shared Debt Ledger from a PR run**.

For a hard proof gate:

```yaml
with:
  strict: true
```

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

The native hooks make the workflow convenient, while the process wrapper remains the stable explicit trust boundary:

```bash
dw guard -- claude
dw guard -- codex
```

Builtin Protect hooks are installed separately and only after explicit opt-in, so Protect can be disabled or delegated without removing the proof/continuity integration.

## IdleProof + Portal

`dw explain` provides the deterministic local evidence-first explanation. Optional user-owned inference can rephrase bounded evidence without changing truth classes.

Portal is an optional commercial coordination/history layer. Its bounded snapshot contract does not require source code, raw prompts, raw diffs, raw commands or raw agent events.

Protect is projected only as aggregate `OBSERVED` runtime metadata and is stored separately from Proof assurance. Guided and Technical Portal views change presentation, not proof semantics.

See [`docs/PRODUCT_SURFACES.md`](docs/PRODUCT_SURFACES.md).

## Security model

DiffWitness executes repository-controlled test/setup commands. Treat those commands with the same trust you would require before running that repository's own test suite.

Disposable Git worktrees isolate code variants from the active checkout. `--share` deliberately links selected paths such as dependency caches and therefore weakens isolation for those paths.

The Protect and Debt Ledger hash chains detect accidental/silent local history mutation; they are **not** external cryptographic signatures proving that a malicious repository owner did not rewrite local metadata.

Core analysis does not require code to leave the machine.

See [`SECURITY.md`](SECURITY.md).

## What DiffWitness does not claim

DiffWitness is not a mathematical proof that software is correct and Protect is not a universal sandbox.

It cannot establish requirements absent from the selected executable evidence. A weak test suite still produces weak evidence. External services can be nondeterministic. Environment differences matter. Security properties can require dedicated analysis.

Debt points are not bug probabilities, percentages of code quality, engineering-hour estimates, confidence probabilities or CVSS.

The intended claim is narrower and useful:

> **Make dangerous agent actions harder to execute accidentally, make it substantially harder for a green check to masquerade as evidence it never provided, and make the remaining obligations difficult to silently forget.**

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
