# Context source references

`dw context "implement partial refunds" --json` selects project memory
relevant to the task. Each selected objective, task, decision, invariant and failed
approach includes a `source` object:

```json
{
  "kind": "project-event",
  "eventId": "<the assertion's existing ProjectEvent ID>",
  "eventHash": "<the assertion's existing SHA-256 event hash>"
}
```

This reference identifies the assertion supplying `details` and `epistemicStatus`.
An unrelated append does not change it. Legacy declarations may inherit a display
label from an earlier assertion; this is not a field-by-field label citation.
An applicability review has its own `lifecycle.sourceEventId` and retains its
`DECLARED` status. A confirmation does not turn an inferred assertion into Proof.

All selected assertions, references and `state.eventHead` are read from one SQLite
snapshot. The head identifies the packet's materialized journal snapshot, not a
promise that no event has arrived since. A missing source or a mismatch between
source and assertion causes a visible error; rebuild Project State with
`dw state rebuild` after investigating the cache. Only selected source rows are
looked up: the subject/sequence index finds each selected entity's latest
projecting event independently of its cached pointer, skipping relation-only,
task-edge and applicability-review events using the projection's predicates.
The assertion timestamp must also match `updatedAt`. Repeated identical
declarations remain distinct sources even when they share a timestamp. This
visits the selected subjects' history until the assertion is found; it does not
scan unrelated subjects, and cost can grow with intervening non-assertion events.

The journal's validated byte digest remains the freshness check. Event hashes
detect changes relative to that journal; they do not authenticate authors or
defend a local database against an owner who can rewrite both journal and cache.
No raw provenance metadata is added to context. Historical applicability to new
code, complete structure/Proof/debt citations and consumer citation presentation
have separate acceptance criteria. Older context consumers can ignore this
additive field without receiving new authority.

Tests and qualification are tracked in [PM-008a1](qualification/PM_008A1.md).
