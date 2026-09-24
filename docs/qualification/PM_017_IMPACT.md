# PM-017: immutable task scope and exact change comparison

This delivers the Core file-scope slice of PM-017.b. It does not close the whole
PM-017 requirement, semantic feature/dependency impact, IdleProof/Portal integration,
release qualification or HUMAN acceptance.

## User journey

Create or select an existing task, then capture the current meaningful Git worktree:

```sh
dw task add "Refactor refund handling" --id TASK-REFUND
dw task impact anticipate TASK-REFUND --file payments/refund.py --file tests/test_refund.py --unknown "Dependency effects remain unmodeled" --json
```

The returned `dwimpact_...` identity and cited event record the anticipated paths,
original task event, immutable base tree, explicit scope and unknowns. Files not
yet created may be anticipated. The existing alternate-index snapshot captures
tracked and meaningful untracked work, preserving the user's staging area; existing
Git-ignore/runtime exclusion rules apply. No native prompt is copied. Repeating an
identical plan is idempotent; changing scope produces a distinct immutable record.
Only `--memory-event` arguments explicitly attach prior objective, invariant,
decision, feature, component, symbol, dependency, debt or Proof event citations.
Citations do not assert that a cited historical property currently applies.

After a real change has been recorded by the existing public Gate/native flow:

```sh
dw task impact compare dwimpact_EXACT_ID dwchg_EXACT_ID --json
dw task impact show TASK-REFUND
dw task impact show dwchg_EXACT_ID --json
```

A plan must precede the observed-change entry in the validated journal. This is
journal order, not authenticated wall-clock or proof that planning preceded every
external action. Plans remain declarations; comparisons remain observations.
Their task/plan/change references include original event hashes. Historical events,
certificates, task identities and Proof authority are never rewritten or promoted.

The comparison freshly inspects the exact Git tree pair, using the existing bounded
read-only tree reader. It records anticipated-and-observed paths, observed paths
outside the plan, absent paths only when coverage is complete, and unresolved
expectations when the base differs or coverage is incomplete. `declared-complete`
is the caller's scope declaration, never a claim of complete semantic understanding.
Missing Git objects produce explicit unavailable coverage. A disagreement between
fresh paths and the cited change is rejected. Effects on cited memory and correctness
remain unknown, even when an independent public certificate is VERIFIED.

`show` navigates from an exact task, plan, comparison or change identity in either
language without changing the journal, database or index. It is bounded to200
records/1MiB; larger histories use the existing cited `dw state history` pages.
There is no new network export, raw source storage or automatic Portal payload.

## Compatibility and qualification

`project-memory-impact-1` is an additive strict profile of the existing ProjectEvent
wire format. Unknown fields, false authority, inconsistent references, after-the-fact
plans and forged deltas are rejected on append and checkpoint import. Old journal
bytes are preserved. An older reader that rejects an unknown strict profile must be
upgraded before reading a journal containing these new events. No destructive migration
or rewriting of historical hashes is performed. The reconstructible SQLite projection
uses the existing generic entity support.

The baseline CLI lacks `task impact`; its actual error is retained. Local tests use
real Git snapshots, actual tree differences and a257-path partial observation, plus
adversarial rehashed inputs, a genuinely missing Git tree, read-only FR/EN CLI and
checkpoint reconstruction. One full-suite invocation from the wrong cwd failed to
import a checkout-only script; that harness failure is retained, then corrected by
using the repository root. All existing assertions remain intact.

`scripts/impact_plan_acceptance.py` exercises an actual installed wheel: task→plan,
real source fix and extra documentation edit, public Gate causal certificate,
exact change→comparison, cited bilingual reads. It asserts that the independently
VERIFIED public Proof does not promote the impact comparison. The existing three-OS
installed-wheel jobs now run this journey; no new runner or publication is involved.

Remaining full-PM requirements include richer semantic impact, automatic context
selection for each category, coordinated IdleProof/Portal interfaces and authenticated
long journeys. PM012 intermittence and full release/HUMAN gates remain open.

Local integrated source:744tests PASS,52explicit skips. Ten focused tests and the actual installed public-Gate journey PASS. Built wheel hash is recorded in PM_017_IMPACT/hashes.json; later documentation changes require a fresh CI artifact identity. Exact final-head review, hosted gates and fresh main remain required.

Final-head CI35937209246 failed all four Windows unit jobs on the new French
assertion. The actual CLI emits UTF-8 (existing stream configuration), while this
test decoded captured bytes through the Windows locale. Explicit UTF-8 decoding
at all three CLI capture boundaries corrects the harness without changing any
assertion or product output. All10focused tests pass locally; fresh Windows CI
is still required. The original Windows3.12 log/job107436803723 is retained;
3.11/job107436803860,3.13/job107436803999,3.14/job107436804056 report the same
single failure among744tests. This is distinct from the open PM012 incidents.
