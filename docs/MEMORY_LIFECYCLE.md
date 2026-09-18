# Reviewing project memory

Decisions, invariants, objectives and failed approaches can outlive the assumptions
behind them. Review their applicability without deleting their original assertion:

```console
dw decision confirm DEC-OLD --reason "Still matches the retry contract"
dw invariant reject INV-OLD --reason "The assumption does not hold for partial refunds"
dw objective retire OBJ-OLD --reason "This feature is no longer planned"
dw decision record "New retry policy" --id DEC-NEW --why "Preserve idempotency"
dw decision supersede DEC-OLD --with DEC-NEW --reason "New policy replaces the earlier choice"
dw decision show DEC-OLD
dw decision show DEC-NEW --view technical
dw failed-approach show FAIL-OLD --json
```

All four commands support `confirm`, `reject`, `retire`, `supersede` and `show`.
IDs above are examples; use records from your project. Add `--repo` to select a
repository. French presentation is available with `dw --language fr ...`.

Confirmation is a **DECLARED review of applicability**, not executed Proof. The
original assertion keeps its own content, source and epistemic status. Guided and
Technical context display these two facts separately. Rejected, retired and
superseded items, and edges through those known inactive items, do not seed active
context. `show` retains their full immutable history and replacement references.

A retired or rejected item can be confirmed again with an explicit reason. A
superseded identity is terminal. Its replacement must be an existing, active item
of the same kind. Once lifecycle management begins, redeclaring the same identity
is rejected; create a new identity and supersede the old assertion instead.

Concurrent actions bind the exact assertion and prior lifecycle revision. A stale
action is rejected; inspect the latest history and decide again. Checksums establish
consistency, not the authenticity of an imported declaration or the identity of the
person behind a CLI invocation. Automated qualification is never HUMAN PASS.
