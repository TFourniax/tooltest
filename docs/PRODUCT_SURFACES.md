# Product surfaces: DiffWitness and IdleProof

DiffWitness and IdleProof share one assurance system but are deliberately **not one user experience**.

## One truth model, two products

### DiffWitness — technical change assurance

Audience: developers, staff engineers, maintainers, security/platform teams and CI systems.

Primary question:

> What does the executable evidence actually establish about this exact software change, and what obligations remain?

DiffWitness owns the authoritative technical primitives:

- Git-bound change identity;
- contrast, necessity, sufficiency, interaction and stability experiments;
- proof certificates;
- deterministic / causal debt signals and the append-only Debt Ledger;
- replay / recheck semantics;
- evidence and policy configuration;
- machine-readable exports for trusted downstream presentation.

The developer UX may become clearer, faster and more visual, but it must never hide completeness limits, inconclusive evidence, budgets or provenance.

### IdleProof — human understanding and action layer

Audience: AI builders, founders, product people and other users who can ship software without wanting to reason in Git hunks, certificates or debt adapters.

Primary question:

> What did my AI change, what is actually known, what is still uncertain, and what should I do next?

IdleProof may:

- translate DiffWitness assurance into plain language;
- show project / feature understanding and longitudinal progress;
- rank next actions;
- show a readiness matrix of done / needs attention / unknown items;
- suggest tests, checks, questions or implementation work;
- produce constrained prompts that a coding agent can execute;
- explain software debt without requiring users to understand the Debt Ledger internals.

IdleProof must not turn a heuristic, an LLM suggestion or missing evidence into a VERIFIED claim.

## Trust vocabulary

Every customer-facing statement that can affect a merge, release or security decision should map to one of these classes:

- **VERIFIED** — established by an executed DiffWitness verification adapter / evidence experiment for the bound change or obligation.
- **OBSERVED** — directly present in bounded project metadata but not a causal proof.
- **SUGGESTED** — recommended next work, test or question. Useful, but not evidence that the work is required or correct.
- **UNKNOWN** — the system does not currently have enough evidence to make the stronger statement.

No presentation layer may silently upgrade OBSERVED, SUGGESTED or UNKNOWN to VERIFIED.

## Architecture boundary

```text
coding agent / human
        |
        v
 local repository
        |
        +-----------------------------+
        |                             |
        v                             v
  IdleProof Local                 DiffWitness
 understanding / intent       causal proof + debt
        |                             |
        +-------------+---------------+
                      |
             bounded local model
                      |
              metadata snapshot
                      |
                      v
              IdleProof Portal
          human UX + longitudinal
          readiness + next actions
```

The Portal is not a second proof engine. It is a commercial coordination and presentation surface over bounded metadata.

## Privacy invariant

The cloud control plane should not require source code, raw prompts, raw diffs or raw agent-event streams to render project state. If a future feature needs a stronger data class, it requires an explicit protocol/version change and a separate privacy review rather than silently widening the current snapshot contract.

## Product rule

Do not solve audience differences by forking assurance semantics.

Additive UX is preferred:

- developers get concise summaries plus drill-down to exact evidence;
- non-technical users get plain-language state plus drill-down to provenance;
- both surfaces resolve to the same change IDs, proof certificates and Debt Ledger obligations when those objects exist.

This keeps the product understandable without creating two incompatible definitions of truth.
