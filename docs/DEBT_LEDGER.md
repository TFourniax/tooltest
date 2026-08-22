# DiffWitness Debt Ledger

> **Your AI ships code. DiffWitness tracks the obligations — and proves when you repay them.**

The Debt Ledger extends DiffWitness's counterfactual proof engine into a persistent software-debt control loop.

It is deliberately **not** a generic maintainability score. A project with 80 points is not claimed to be “20% worse” than a project with 64 points.

A debt item is an explicit **future engineering obligation** with stable identity, provenance, a bounded claim and — where possible — a replayable verification procedure.

## Product loop

```text
agent / human changes code
          ↓
DiffWitness proof / assurance
          ↓
measure explicit obligations
          ↓
append to Debt Ledger
          ↓
plan / repay mission
          ↓
independent Gate
          ↓
replay the original debt claim
          ↓
close only if verified
```

A green build cannot by itself answer all of these questions:

- Which parts of this patch are actually witnessed by executable evidence?
- Did candidate tests distinguish the old behavior from the new behavior?
- Did the change add redundant implementation paths?
- Did it expand dependency, migration, architecture or security-sensitive surface?
- Which obligations were introduced by a particular agent/change?
- Did a later cleanup truly remove the obligation, or merely make a scanner quiet?

The ledger is useful because it preserves the *claim and how to replay it*, rather than just preserving a score.

## Stable lineage

Every obligation has a stable `DW-...` identity derived from semantics such as category, rule, path and anchor — not from mutable wording or point value.

A lineage can therefore evolve:

```text
introduced
    ↓
refreshed with better evidence
    ↓
accepted with explicit reason
    ↓
rechecked
    ↓
resolved with verification
    ↓
reappears
    ↓
reopened (same DW identity)
```

A ledger item contains fields such as:

```text
DW-3A7C...          stable lineage id
category            evidence / test / security / ...
rule_id             why it exists
measurement         causal / deterministic / historical / heuristic
points              accounting weight
path + line         when meaningful
introduced_by       Git / certificate / agent provenance
evidence             what was observed
verification         how the claim can be replayed
status               open / resolved
accepted             acknowledged debt remains debt
history              append-only lifecycle
```

## Measurement provenance

DiffWitness separates four kinds of knowledge so a weak signal cannot masquerade as a strong one.

### `causal`

Produced by a controlled DiffWitness counterfactual experiment.

Examples:

- a real candidate mutation was removed and the selected evidence stayed stably green;
- exhaustive sufficient-set search established a strong surplus candidate;
- Adaptive Core found a stable-passing real-patch core that excludes a mutation;
- two mutations form a tested mutual-backup pair;
- changed tests pass on both historical base and candidate and therefore fail to discriminate the change.

These are strong *bounded* claims, not mathematical correctness proofs.

### `deterministic`

Derived from an exact reproducible repository/diff property without claiming causality.

Examples:

- executable change lacks accepted DiffWitness behavioral evidence;
- an exact normalized code block appears in several files;
- the resolved local-relative-import graph contains a cycle;
- a specific injection-sensitive syntax sink appears;
- a production diff crosses a structural threshold.

### `historical`

Derived by replaying current evidence against the historical introducing base/candidate pair.

For example, old test debt can close when today's test surface proves:

```text
historical base + current tests        STABLE FAIL
introducing candidate + current tests  STABLE PASS
```

### `heuristic`

A deliberately weaker review obligation.

Examples:

- a sensitive-looking module has no conventionally named test companion;
- a migration contains no recognized rollback marker;
- a change sharply increases local import fan-out;
- a large implementation change has no knowledge-artifact update.

Every heuristic should explain what it **does not** prove.

## Categories

| Category | Intended obligation |
|---|---|
| `evidence` | selected behavioral evidence does not establish necessity, or proof is inconclusive |
| `test` | change-specific regression/discrimination evidence is missing or weak |
| `complexity` | review/rollback/understanding surface grew materially |
| `redundancy` | implementation surfaces appear duplicated or behaviorally redundant |
| `dependency` | external maintenance/supply-chain surface expanded |
| `architecture` | coupling or boundary pressure increased |
| `security` | injection/auth/permission/secret-sensitive surface deserves explicit verification |
| `migration` | data/schema transition creates a recovery obligation |
| `knowledge` | project evolution outpaces an obvious knowledge-transfer artifact |
| `unverified_change` | executable production change lacks accepted DiffWitness behavioral evidence |

## Point semantics

Default accounting weights:

```text
info       0
low        1
medium     3
high       5
critical   8
```

A point is **not**:

- a predicted bug;
- a percentage of code quality;
- an estimate of engineering hours;
- a confidence probability;
- CVSS or another security standard.

Points are a budgetable accounting abstraction over inspectable obligations.

## Local event-sourced ledger

The default local ledger is:

```text
.git/diffwitness/debt-ledger.jsonl
```

Each line is an event chained to the preceding event with SHA-256:

```text
introduced
refreshed
accepted
unaccepted
resolved
reopened
```

The current alpha hardens this storage layer in several ways:

- atomic replacement prevents readers from seeing a partially written JSONL file;
- the temporary file and directory entry are flushed where supported;
- an inter-process lock serializes local writers;
- a stale process re-reads the latest disk history before deciding/appending;
- state decisions and event append happen under the same lock;
- an imported hash-valid history is also checked for semantically valid transitions;
- a debt payload must reproduce the same stable `DW-...` identity as the event that carries it.

The hash chain is an integrity mechanism. It is **not a digital signature** against a malicious owner who can deliberately rewrite the entire history.

## Portable ledger checkpoints

A clone-local ledger is not enough for ephemeral CI or a second developer machine. DiffWitness can store a checkpoint on a dedicated Git ref:

```text
refs/diffwitness/debt-ledger
```

The checkpoint is a normal Git commit containing `ledger.jsonl`, but it is not part of the source branch and does not rewrite `HEAD`.

### Inspect local relationship

```bash
dw ledger status
```

### Create/update a local checkpoint ref

```bash
dw ledger checkpoint
```

Repeated checkpointing of unchanged ledger bytes is idempotent.

### Restore from a remote

```bash
dw ledger pull
```

Defaults:

```text
remote = origin
ref    = refs/diffwitness/debt-ledger
```

Use a different remote/ref when required:

```bash
dw ledger pull \
  --remote upstream \
  --ref refs/diffwitness/team-ledger
```

If a remote ref genuinely does not exist, the default pull treats that as first use. To require a pre-existing shared baseline:

```bash
dw ledger pull --required
```

Authentication, network, repository and other Git transport errors never become “empty ledger” fallbacks.

### Publish a checkpoint

```bash
dw ledger push
```

Push is deliberately **non-force**. If another writer advanced the remote, the push fails. Pull/reconcile before retrying.

Two event histories that diverged after a common prefix are not automatically merged. DiffWitness refuses to guess which state transition ordering is authoritative.

### Recommended CI trust split

**Pull request / untrusted candidate execution:**

```text
read shared ledger baseline
prove candidate
measure projected debt
fail/pass policy
DO NOT push shared ledger
```

The provided composite GitHub Action follows this model.

**Trusted default-branch/post-merge workflow:**

```bash
dw ledger pull --required   # optional --required after bootstrap
# record the accepted change and/or reconcile project health
dw debt --base <before> --candidate <after> --certificate evidence.json
dw health
dw ledger push
```

Only the trusted workflow should receive credentials capable of updating the checkpoint ref.

## `dw debt`

Measure a change:

```bash
dw debt --base origin/main --candidate HEAD
```

With proof evidence:

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

A supplied certificate must pass integrity and candidate-content binding before debt accounting trusts it.

**Certificate presence is not evidence.** Validation-only, inconclusive, forged, unbound or non-discriminating certificate data cannot suppress the main `unverified_change` obligation.

`dw debt` records lineages unless `--no-record` is supplied.

## `dw health`

```bash
dw health
```

Project health is scanned from an immutable snapshot of the **current worktree**. This matters on dirty repositories: findings are bound to the exact tree that was inspected instead of being labelled with `HEAD` while reading different bytes.

The project scan currently looks for bounded properties such as:

- exact normalized duplicate blocks across source files;
- resolved cycles through local relative imports;
- very large source files;
- deterministic security-sensitive syntax patterns;
- sensitive modules without an obvious conventionally named test companion.

Project-rule debts can reconcile automatically: when the exact rule no longer reproduces, the lineage closes with an `absent` verification record.

## `dw plan`

```bash
dw plan
```

Builds a deterministic priority set from open, unaccepted debt. Causal items are preferred over weaker heuristics at comparable weight.

The selected point total is not a duration estimate or guaranteed reduction.

## `dw repay`

```bash
dw repay -- claude
```

or:

```bash
dw repay DW-123... DW-456... -- codex
```

The agent mission is constrained:

- preserve currently validated behavior unless the obligation requires behavior correction;
- touch only what is necessary for listed obligations;
- avoid dependencies unless genuinely required;
- add regression evidence for evidence/test debt;
- prefer deleting redundant surface over gaming a metric;
- never edit the Debt Ledger directly.

After the agent exits, DiffWitness independently:

1. snapshots the resulting candidate;
2. runs the normal Gate;
3. measures debt introduced by the repayment patch;
4. records new obligations;
5. replays each selected debt's verification adapter;
6. resolves only positively verified items;
7. recomputes the final debt budget;
8. rejects the repayment if selected debts remain unresolved or new open debt appears, unless explicitly allowed.

## Replay adapters

### Mutation necessity

If a lineage originated because real mutation `H17` was removable:

```text
current candidate                 STABLE PASS
current candidate - old H17       STABLE FAIL
```

then the mutation is now behaviorally witnessed and the obligation can close.

Control-run side effects are cleaned before the counterfactual replay so a test-generated cache/fixture cannot create a false causal difference.

If the current evidence stays green without `H17`, the item remains open. If the old patch relationship no longer applies cleanly in either direction, replay is inconclusive rather than guessed.

### Historical test discrimination

For test debt, current tests can be overlaid independently onto the historical introducing base and candidate. The lineage resolves only under stable historical `base-fail / candidate-pass` contrast.

### Project rule

The current project snapshot is rescanned and the exact stable debt identity is checked. Absence closes the project-rule lineage; presence keeps it open.

## `dw recheck`

```bash
dw recheck DW-7821
```

or:

```bash
dw recheck --all
```

Unsupported, unavailable, flaky or timed-out replays remain inconclusive.

## Ledger inspection and governance

```bash
dw ledger list
dw ledger list --all
dw ledger show DW-7821
dw ledger history DW-7821
```

Accept intentional debt:

```bash
dw ledger accept DW-7821 \
  --reason "temporary provider migration; removal scheduled after cutover"
```

Undo acceptance:

```bash
dw ledger unaccept DW-7821
```

A manual resolution is intentionally explicit and marked forced:

```bash
dw ledger resolve DW-7821 \
  --reason "verified outside DiffWitness; incident record ABC-123" \
  --force
```

Prefer `dw recheck` whenever an automatic evidence-backed adapter exists.

## Debt Budget

Example:

```toml
[debt]
max_total = 100
max_per_change = 12

[debt.security]
max = 10

[debt.evidence]
max = 30
```

A functionally accepted change can therefore still be rejected for exceeding an explicit future-obligation budget.

The configuration parser fails closed on unknown debt keys and invalid limits.

## Guard integration

After public Gate accepts an agent patch, Guard measures/records debt and can reject the session for a budget violation.

Conservative provenance can include:

```json
{
  "source": "guard",
  "agent": "claude-code",
  "executable": "claude"
}
```

Prompts and full command arguments are intentionally not persisted because they can contain secrets or private data.

## GitHub Action integration

The composite action exposes:

```text
certificate_id
debt_points
debt_projected_total
debt_budget_passed
```

By default it restores `refs/diffwitness/debt-ledger` before debt-budget evaluation. A truly absent checkpoint means bootstrap/first use; a transport/auth failure fails the action instead of silently resetting debt history.

The action runs `dw debt --no-record`: it computes projected debt but does **not** mutate/publish the shared ledger from the PR execution context.

Proof and debt JSON are preserved together when artifact upload is enabled.

## Boundaries and non-claims

The Debt Ledger cannot prove that every product requirement exists in the selected tests.

It cannot infer product intent from a diff with certainty.

It cannot turn a security-sensitive syntax match into proof of exploitability.

It cannot know a dependency is unnecessary merely because a manifest changed.

It cannot prove every migration without a recognized down marker is irreversible.

It cannot reconstruct a historical claim when required Git objects/evidence are unavailable or code diverged beyond the replay boundary.

A hash-chained local/Git ledger is not equivalent to externally signed attestation.

Those boundaries are part of the product: DiffWitness should prefer **unknown**, **inconclusive** or **heuristic** over a more impressive but unjustified claim.
