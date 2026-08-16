# DiffWitness Debt Ledger

> **Your AI ships code. DiffWitness tracks the debt — and proves when you repay it.**

The Debt Ledger is an experimental layer built on top of DiffWitness's counterfactual proof engine.

It is deliberately **not** a generic maintainability score and it is not a claim that a codebase with 80 points is "20% worse" than a codebase with 64 points.

A debt item is an explicit **future engineering obligation** with provenance, a bounded claim, and — where possible — a replayable verification procedure.

## Why this exists

AI coding makes code generation cheap. The scarce resource becomes confidence about what was generated:

```text
agent generates code
        ↓
proof / assurance
        ↓
measure explicit obligations
        ↓
Debt Ledger
        ↓
repay mission
        ↓
independent Gate
        ↓
replay the original debt claim
        ↓
close only if verified
```

A green build is useful, but it does not answer all of these questions:

- Which parts of this patch are actually witnessed by executable evidence?
- Did new tests distinguish the old behavior from the new behavior?
- Did the change introduce redundant implementation paths?
- Did it expand a dependency, migration, architecture, or security-sensitive surface?
- Which obligations were introduced by this agent session?
- Did a later cleanup really remove the obligation, or merely make a static warning disappear?

DiffWitness's existing proof engine gives the Ledger a stronger foundation than a static score alone: some debt can be linked to controlled experiments on the real Git patch.

## The score is not the moat

A Debt Ledger item has a stable `DW-...` identity. The aggregate point total is only a compact view over those items.

Every item carries:

```text
DW-3A7C...                 stable lineage id
category                   evidence / test / ...
rule                       why the item exists
measurement                causal / deterministic / historical / heuristic
points                     accounting weight
path + line                 when meaningful
introduced_by              Git and agent provenance when known
evidence                    what was observed
verification                how the claim can be replayed
status                      open / resolved
accepted                    acknowledged debt remains debt
history                     append-only lifecycle
```

The useful data is the lineage and its verification history, not the number printed at the top of `dw health`.

## Measurement provenance

DiffWitness intentionally separates four kinds of knowledge.

### `causal`

Produced by a controlled DiffWitness counterfactual experiment.

Examples:

- a real candidate hunk was removed and the evidence stayed stably green;
- exhaustive sufficient-set search established a strong surplus candidate;
- Adaptive Core found a stable-passing real-patch core that does not contain a mutation;
- two mutations are a tested mutual-backup pair;
- changed tests pass on both old and new code, so they do not discriminate the production change.

These are the strongest Debt Ledger claims, but they are still bounded by the chosen evidence command and environment.

### `deterministic`

Derived from an exact, reproducible property of the repository or diff without claiming causality.

Examples:

- an executable change has no supplied DiffWitness certificate;
- an exact normalized code block appears in several files;
- a resolved graph of local relative imports contains a cycle;
- a specific injection-sensitive sink was introduced;
- the production diff exceeds a configured structural threshold.

### `historical`

Derived by replaying current evidence against a historical introducing base/candidate pair.

A particularly important example is test debt. Suppose feature code was introduced without a discriminating regression test. Weeks later DiffWitness can carry the **current test change** back to the historical commits:

```text
historical base + current tests       STABLE FAIL
introducing candidate + current tests STABLE PASS
```

That is direct evidence that the later tests now witness the original behavior change.

### `heuristic`

A deliberately weaker review obligation.

Examples:

- a sensitive-looking module has no conventionally named test companion;
- a migration contains no rollback/down/reverse marker recognized by DiffWitness;
- a change sharply increases relative import fan-out;
- a very large production change has no knowledge artifact update.

A heuristic must say what it **does not** prove. It must never be presented as a vulnerability, defect, or causal fact merely because it contributes points.

## Categories

The experimental schema currently defines:

| Category | Intended obligation |
|---|---|
| `evidence` | code exists but selected behavioral evidence does not establish its necessity, or proof remains inconclusive |
| `test` | change-specific regression/discrimination evidence is missing or weak |
| `complexity` | review/rollback/understanding surface grew materially |
| `redundancy` | multiple implementation surfaces appear to carry equivalent behavior or duplicate code |
| `dependency` | external maintenance/supply-chain surface expanded |
| `architecture` | module coupling or boundary pressure increased |
| `security` | injection/auth/permission/secret-sensitive surface deserves explicit verification |
| `migration` | data/schema transition creates a recovery obligation |
| `knowledge` | project evolution outpaces an obvious knowledge-transfer artifact |
| `unverified_change` | executable production change has no supplied DiffWitness proof/assurance certificate |

The categories are intentionally broad; each debt item must still have a specific `rule_id` and bounded explanation.

## Point semantics

Default accounting weights are currently:

```text
info       0
low        1
medium     3
high       5
critical   8
```

They are deliberately simple.

A point is **not**:

- a predicted bug;
- a percentage of code quality;
- an estimate of engineering hours;
- a confidence probability;
- a security severity standard such as CVSS.

The point total is a budgetable accounting abstraction over inspectable obligations.

## Event-sourced ledger

The default Ledger lives under:

```text
.git/diffwitness/debt-ledger.jsonl
```

That keeps local bookkeeping outside the candidate Git diff by default.

Each line is an append-only event chained to the previous event by a hash:

```text
introduced
refreshed
accepted
unaccepted
resolved
reopened
```

The hash chain detects accidental or silent ledger mutation. It is **not a cryptographic signature** proving that the repository owner did not deliberately rewrite history.

For stronger cross-party authenticity a future layer should sign/attest ledger checkpoints externally.

## Stable lineage

A debt identity is derived from stable semantics such as category, rule, path and anchor — not from its current point value or wording.

That means an obligation can evolve without losing its history:

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

## `dw debt`

Measure a change:

```bash
dw debt --base origin/main --candidate HEAD
```

With a proof certificate:

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

A supplied certificate must pass the Debt Ledger's integrity/content-binding validation before it can suppress verification debt.

Typical output:

```text
Debt impact: +13 point(s) across 4 obligation(s)
  evidence           +3
  redundancy         +5
  security           +5

DW-... +5 redundancy/causal src/billing.py:94 — Strong surplus candidate
DW-... +5 security/heuristic src/billing/webhook.py — Sensitive surface changed without accepted behavioral evidence
DW-... +3 evidence/causal src/billing.py:117 — Behaviorally unwitnessed change

Budget: PASS — projected total 81; new 13
```

`dw debt` records lineages unless `--no-record` is supplied.

## `dw health`

Project-level scan + Ledger view:

```bash
dw health
```

The project scan currently looks for bounded properties such as:

- exact normalized duplicate blocks across files;
- local relative-import cycles;
- very large tracked source files;
- deterministic security-sensitive syntax patterns;
- sensitive modules without an obvious conventionally named test companion.

Project-rule debts can be reconciled automatically: when the exact project rule no longer reproduces, the corresponding lineage can close with an `absent` verification record.

## `dw plan`

```bash
dw plan
```

Builds a deterministic priority set from open, unaccepted debt. Causal items are preferred over weaker heuristics at comparable weight.

The displayed point total is **not an estimate of implementation time or guaranteed reduction**.

## `dw repay`

```bash
dw repay -- claude
```

or:

```bash
dw repay DW-123... DW-456... -- codex
```

The mission sent to the agent is deliberately constrained:

- preserve validated behavior;
- touch only what is necessary for the listed obligations;
- avoid new dependencies unless the debt requires one;
- add regression evidence for evidence/test debt;
- prefer deleting redundant surface over gaming a metric;
- never edit the Debt Ledger directly.

After the agent exits, DiffWitness independently:

1. captures the resulting candidate;
2. runs the normal Gate;
3. measures debt introduced by the repayment patch;
4. replays the original verification adapter for every selected debt;
5. resolves only debts whose original claim is no longer true or has become positively witnessed;
6. recomputes Debt Budget;
7. rejects repayment if selected debts remain unresolved or new open debt was introduced, unless explicitly allowed.

This is the central product loop:

```text
GENERATE
   ↓
MEASURE
   ↓
REPAY
   ↓
PROVE
   ↓
REPLAY THE ORIGINAL DEBT CLAIM
   ↓
MEASURE AGAIN
```

## Replayable repayment

### Mutation necessity replay

If debt originated because mutation `H17` was removable, DiffWitness stores the exact real mutation patch.

Later, against the current stable-green candidate:

```text
current candidate                 STABLE PASS
current candidate - old H17       STABLE FAIL
```

The original debt can close: the mutation is now behaviorally witnessed by current evidence.

If the evidence stays green without it, the debt remains open.

If the old patch is no longer present at all, DiffWitness can close the old mutation lineage when the patch relationship proves that the debt-carrying implementation disappeared.

If current code diverged so far that neither side of the old patch can be reconstructed, the result is `inconclusive`, not a fake resolution.

### Historical test-discrimination replay

For test debt, DiffWitness can replay current tests against the historical introducing base and candidate. This lets a project repay an old "feature had no regression evidence" obligation without pretending that today's tests existed at introduction time.

## `dw recheck`

Re-run verification adapters without invoking an agent:

```bash
dw recheck DW-7821
```

or:

```bash
dw recheck --all
```

Only verified resolutions are closed automatically. Unsupported or unstable replays remain inconclusive.

## Accepted debt

Sometimes debt is deliberate:

```bash
dw ledger accept DW-7821 --reason "temporary provider migration; removal scheduled after cutover"
```

Accepted debt:

- remains in the Ledger;
- still contributes to the total by default;
- retains its reason and history;
- is skipped by the default repayment planner.

Acceptance is governance, not deletion.

## Debt Budget

Example configuration:

```toml
[debt]
max_total = 100
max_per_change = 12

[debt.security]
max = 10

[debt.evidence]
max = 30
```

A change can therefore be functionally correct under the selected proof policy but still exceed an explicit debt budget.

The intended principle is:

> Agents may generate as much code as necessary, but they do not have an unlimited budget for future verification and maintenance obligations.

The config parser fails closed on unknown debt keys and invalid limits rather than silently changing budget semantics.

## Guard integration

`dw guard` now measures Debt Ledger impact immediately after the public Gate accepts the agent patch:

```bash
dw guard -- claude
```

The lineage stores conservative provenance such as:

```json
{
  "source": "guard",
  "agent": "claude-code",
  "executable": "claude"
}
```

Prompts and full command arguments are intentionally not persisted by default because they can contain secrets or private user data.

A debt budget can reject Guard even after proof passes.

## GitHub Action integration

The experimental action exposes both proof and debt outputs:

```text
certificate_id
debt_points
debt_projected_total
debt_budget_passed
```

The action first proves the patch and then runs debt accounting against the same base/candidate pair and proof certificate. Configured debt budgets can fail the PR.

Proof and debt JSON are preserved together as workflow artifacts when artifact upload is enabled.

## What DiffWitness deliberately does not claim

The Debt Ledger cannot prove that every requirement is represented in the selected tests.

It cannot infer product intent from a diff with certainty.

It cannot turn a regex/security-sensitive syntax match into proof of an exploitable vulnerability.

It cannot know that a dependency is unnecessary merely because a manifest changed.

It cannot know that every migration without a recognized `down` marker is irreversible.

It cannot reconstruct a historical claim when the required Git objects/evidence are gone or the code has diverged beyond the stored replay boundary.

And a local content-addressed certificate or hash-chained ledger is not equivalent to an externally signed attestation against a malicious repository owner.

Those boundaries are part of the product. DiffWitness should prefer **unknown** or **heuristic** over a more impressive but unjustified score.
