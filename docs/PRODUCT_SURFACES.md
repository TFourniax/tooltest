# Product surfaces: DiffWitness and IdleProof

DiffWitness and IdleProof share one assurance system but are deliberately **not one fixed user experience**.

## One truth model, two product entry points

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

## Reversible experience level

Product entry point and experience level are separate decisions.

A user can enter through IdleProof and later ask for engineering detail. A developer can enter through DiffWitness and later prefer a simpler project summary. No reinstall, migration, duplicate project or second proof run is required to move between those levels.

The supported human-facing levels are:

- **Guided** — plain language, consequences, unknowns and recommended actions first. Exact provenance remains available through progressive disclosure.
- **Technical** — exact assurance terminology, Git/change identity, proof scope, certificate/provenance detail, Debt Ledger accounting and engineering commands first.

Switching levels changes **presentation only**. It must never change:

- the bound change;
- proof execution or acceptance;
- certificate contents;
- Debt Ledger history or policy;
- readiness inputs;
- machine-readable status contracts;
- privacy boundaries.

For the local DiffWitness experience, `dw view guided` and `dw view technical` persist the preference under `.git/diffwitness/`; `dw status --view ...` provides a one-off override. Existing DiffWitness installations default to Technical for backward compatibility. The `dw status --json` contract is deliberately view-invariant.

IdleProof Portal defaults to Guided because it is the non-technical product entry point, while Technical remains available from the global application shell and can be reversed at any time.

## Trust vocabulary

Every customer-facing statement that can affect a merge, release or security decision should map to one of these classes:

- **VERIFIED** — established by an executed DiffWitness verification adapter / evidence experiment for the bound change or obligation.
- **OBSERVED** — directly present in bounded project metadata but not a causal proof.
- **SUGGESTED** — recommended next work, test or question. Useful, but not evidence that the work is required or correct.
- **UNKNOWN** — the system does not currently have enough evidence to make the stronger statement.

No presentation layer may silently upgrade OBSERVED, SUGGESTED or UNKNOWN to VERIFIED. Guided mode may translate these labels, but the underlying class must remain inspectable.

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
                 /          \
            Guided       Technical
```

The Portal is not a second proof engine. It is a commercial coordination and presentation surface over bounded metadata.

## Privacy invariant

The cloud control plane should not require source code, raw prompts, raw diffs or raw agent-event streams to render project state. If a future feature needs a stronger data class, it requires an explicit protocol/version change and a separate privacy review rather than silently widening the current snapshot contract.

## Product rule

Do not solve audience differences by forking assurance semantics or by trapping a user in the persona chosen during onboarding.

Additive UX is preferred:

- developers get concise summaries plus drill-down to exact evidence;
- non-technical users get plain-language state plus drill-down to provenance;
- either user can switch the default disclosure level at any time;
- both surfaces resolve to the same change IDs, proof certificates and Debt Ledger obligations when those objects exist.

This keeps the product understandable without creating two incompatible definitions of truth.
