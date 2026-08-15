# DiffWitness Proof Protocol (DWPP) v1

DiffWitness is not a test runner and not an AI reviewer. It is an experimental **proof layer for code changes**.

A normal CI check answers:

> Did this command return zero on the candidate?

A DiffWitness proof attempts to answer a stronger, explicitly bounded question:

> Under this executable evidence and environment, what relationship can we demonstrate between the pre-change state, the candidate patch, and the observed behavior?

This document defines the portable semantics behind that claim. The protocol is intentionally model-agnostic: a patch may come from Claude Code, Codex, a human, a script, or another agent.

## 1. Proof subject

Every proof binds to:

- an exact Git **base** commit/snapshot;
- an exact Git **candidate** commit/snapshot;
- the real diff between them;
- an **evidence command**;
- the configuration used to run the experiment;
- observed outcomes rather than model judgments.

The patch itself is the mutation surface.

## 2. Evidence predicates

### Candidate stability

The candidate must pass the evidence command consistently for the configured repetitions.

Possible run classifications:

- `stable-pass`
- `stable-fail`
- `flaky`
- `timeout`

A flaky or timed-out variant is never promoted to a causal conclusion.

### Contrast

When candidate test changes can be separated from production changes, DiffWitness overlays the candidate tests onto the base and evaluates:

```text
base + candidate tests        FAIL
candidate + candidate tests   PASS
```

`base-fail_candidate-pass` is **bug-discriminating evidence** for the whole patch under the selected command.

A base that already passes is not silently treated as equivalent proof.

### Hunk necessity

For each real production hunk `H`:

```text
candidate - H  -> evidence
```

- `witnessed`: removing `H` makes evidence stably fail;
- `unwitnessed`: evidence stays stably green;
- `inconclusive`: the experiment cannot support a causal claim.

Necessity is always relative to the chosen evidence. It is not a claim that unwitnessed code is globally useless.

### Sufficient core

When contrast exists, DiffWitness can start from `base + candidate tests`, add real production hunks, and search for the smallest tested subset that makes evidence stably pass.

The result is a **minimal-cardinality sufficient evidence core inside the explored search space**.

The certificate records whether the discovered cardinality was exhaustively enumerated. A non-exhaustive search must never be presented as a global minimum.

### Interaction

Individual ablation can hide redundancy:

```text
candidate - A       PASS
candidate - B       PASS
candidate - A - B   FAIL
```

DiffWitness reports `A + B` as `mutual-backup`. Neither change is independently necessary, but the pair collectively carries evidence.

## 3. Exhaustive vs budgeted proof

Every combinatorial search is bounded. A proof certificate must expose:

- whether a search was enabled;
- the number of variants attempted;
- the configured budget;
- the order/cardinality explored;
- whether the relevant search frontier was exhaustive.

**Unknown must remain unknown.** Budget exhaustion is metadata, not permission to manufacture certainty.

This principle is non-negotiable for future adaptive/large-patch modes.

## 4. Proof policies

The protocol separates **evidence** from **policy**.

A team may interpret the same evidence differently without changing the underlying certificate.

DiffWitness Guard currently exposes three policies:

### `observe`

Never blocks. Generates evidence and lets the user decide.

### `balanced`

Blocks unstable/inconclusive evidence and strong surplus candidates, while allowing individually unwitnessed hunks when they may represent requirements outside the selected command.

### `strict`

Requires stable base-fail -> candidate-pass contrast and rejects any unwitnessed or inconclusive analyzed hunk.

Policies are intentionally downstream of the experiment. The certificate should remain useful even when organizational policy changes.

## 5. Proof-carrying agent sessions

`dw guard -- <agent>` defines an agent-agnostic transaction:

```text
capture pre-agent repository state
            |
            v
run Claude / Codex / human tool interactively
            |
            v
capture final repository state
            |
            v
run counterfactual proof over the exact produced diff
            |
      +-----+-----+
      |           |
   ACCEPT       REJECT
```

The agent does not self-certify. The proof layer observes the artifact after generation.

Lifecycle plugins can automate the same transaction at `SessionStart` / `Stop`. The wrapper remains the reference path because it does not depend on a particular agent runtime's hook behavior.

## 6. Certificate requirements

A machine-readable certificate should contain enough information to answer:

- What exact code states were compared?
- What executable evidence was used?
- Was the candidate stable?
- Did the evidence discriminate base from candidate?
- Which hunks were necessary under that evidence?
- Which subsets were sufficient?
- Which interactions were discovered?
- Which searches were exhaustive or budget-limited?
- What environment produced the observation?
- What did the tool explicitly *not* prove?

The current JSON schema lives at `schema/diffwitness-report-v2.schema.json`. Future schema versions must preserve the rule that uncertainty and search completeness are explicit fields, not inferred from missing data.

## 7. Threat model / non-claims

DiffWitness does **not** prove that software is correct in the mathematical sense.

It cannot establish requirements that the selected evidence does not encode. It can be fooled by bad tests, nondeterministic external systems, malicious repository test commands, environment mismatch, or behavior outside the tested surface.

Its value is narrower and practical: it makes the relationship between a patch and its claimed executable evidence substantially harder to fake accidentally.

## 8. Design invariants

Future DiffWitness features should preserve these invariants:

1. **Model independence** — no LLM is required to establish the core proof.
2. **Local-first** — source code need not be uploaded to a DiffWitness service.
3. **Real-patch experiments** — synthetic mutation may supplement but never replace real-diff analysis.
4. **Counterfactual evidence** — candidate-green alone is not sufficient for a causal claim.
5. **Uncertainty is first-class** — flakiness, timeouts and budget limits remain visible.
6. **Evidence/policy separation** — measurements are portable; merge policy is configurable.
7. **No hidden deletion** — DiffWitness may propose a reduction but never silently rewrites the user's working tree.
8. **Agent independence** — the same proof semantics apply to human and machine-generated changes.

## 9. The intended social convention

The long-term goal is simple:

> “Tests pass” should cease to be the strongest evidence attached to a code-changing agent task.

A high-trust change should be able to carry its proof certificate alongside the diff, regardless of who or what generated it.
