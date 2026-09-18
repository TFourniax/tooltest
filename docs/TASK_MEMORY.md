# Durable task memory

Native prompt hooks preserve the existing task identity across short follow-ups.
An explicit pivot starts another task. The durable journal saves the identity,
prompt digest and length, session digest and ordinal; it does not automatically
save the prompt, its shortened anchor, the session identifier or the current focus.
Digests are identifiers, not anonymization guarantees or evidence of intent.

Each armed native session boundary has a distinct ID. Its recorded participants
are linked to the exact change observed by the Stop handoff. If several tasks
participated, all are retained. This `OBSERVED` association means “worked on in
this boundary”; it does not prove which task caused a hunk or that a task is done.
Proof remains separately bound to the exact candidate tree.

Save a readable description only when you want that text in project history:

```console
dw task add "Preserve refund idempotency" --id TASK-REFUND --why "Avoid duplicate payouts"
dw task describe dwtask_<id> --title "Partial refunds" --why "Explicitly saved intent"
dw task link TASK-REFUND dwchg_<id> --why "Implements the refund task"
dw task show TASK-REFUND
dw task show TASK-REFUND --view technical
dw task show TASK-REFUND --json
dw context TASK-REFUND --json
```

Replace placeholder IDs with IDs from your own project. Use `--repo` to select a
repository and `dw --language fr task ...` for French presentation. JSON facts
retain the same language-independent schema. Explicit links are `DECLARED`
intent, not executed Proof. Descriptions append history without changing identity.
Deleting temporary prompt context does not delete durable task/change history.

Old native state without a boundary ID remains readable but cannot retroactively
establish native participation. Missing or invalid references reject the whole
change import. A participant-recording failure marks memory degraded; subsequent
success for a different task does not erase the missed participant. Diagnose with
`dw doctor` and preserve the original envelope; a rebuild alone cannot invent a
missing association. Explicitly declared links can document known intent later.

This Core implementation does not yet provide a shared IdleProof/Portal task UI.
Their consumer adoption and release qualification are tracked in registry #74.
