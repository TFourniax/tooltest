# Debt report Git identity admission

The historical Debt Ledger bridge used `git rev-parse` without `--verify` on a
report-supplied base string. Git can echo an unknown option-like argument and exit
successfully. The bridge then hashes that echoed text into an invented change ID
and records an OBSERVED debt-to-change relationship. Disposable real-Git probes
reproduce this for `--not-a-reference` and `--all`; a missing ordinary ref already
returned no identity. This is a false attribution defect, distinct from #120's
local file-write issue in the change-envelope importer.

The correction accepts only full lowercase SHA-1/SHA-256 base object identities
and a reported candidate tree of the same object-format length. Mutable ref names,
option-like strings, malformed tree IDs and unavailable bases cannot establish a
historical change link. The bounded read-only Git runner uses explicit verification,
end-of-options, no replacement objects/lazy fetch/prompts, at most 65 output bytes
and a 15-second deadline. The resulting tree identity is validated again.

An unavailable/invalid historical base preserves the original debt event, original
authority and source hash but records no change ID or relationship. It remains
idempotent. A process/output/time-budget failure rejects before the event batch is
appended. The candidate tree remains the identity reported by the debt artifact;
this does not verify its content or manufacture executed Proof. Normal native
reports already contain full immutable object IDs and keep their existing IDs.

Existing immutable ProjectEvents are not rewritten or resealed. A re-import that
conflicts with an earlier invented linkage still rejects the semantic conflict;
historical correction/migration is not silently performed. This bounded repair
does not close complete longitudinal debt/Proof attribution or release readiness.

Two new real-Git regression tests retain debt without the fake relationship and
check option-like/mutable/missing/malformed/mixed-format identities alongside a
valid exact base/tree pair. The previous installed wheel fails seven assertions;
the corrected targeted suite passes all four bridge tests. Existing lifecycle
profile tests also pass. An initial exploratory invocation used a Python without
the package and failed import; the actual product reproduction used the installed
wheel. No product finding is inferred from that environment error.

The change is developed separately and stacked on #120 so the integrated product
can be qualified once, while each bounded correction remains independently
reviewable. PR/main machine evidence and remaining coordinated gates are tracked
in registry #74. All automated evidence remains MACHINE, never HUMAN.

The integrated wheel (including corrected #120 head 0dafa160be9158e49766201035849a0db87b3750)
passes all 708 installed tests, with 52 explicit platform/optional-provider skips,
in 69.372 seconds. The changed debt bridge and all four #120 product modules are
byte-equal between source, wheel and installation. Exact hashes and the lossless
full-suite archive are recorded in `evidence/DEBT_GIT_IDENTITY_local.json`.
