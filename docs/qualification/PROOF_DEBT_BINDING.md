# Public certificate families consumed by Debt

Registry #74; audit B/F-01/AD-10 (C2). Baseline
`4501e91275a07492447c1276e940b0fb936e230e`.

Debt treated adaptive `candidate` (a test result) as a Git binding and rejected
the real certificate already accepted by `dw verify`. A shared family-aware
reader now uses the authenticated binding location, validates object identity
syntax, and rejects conflicting alternate fields and unknown declared schemas.
Historical missing version fields remain supported. Hash algorithms, certificates
and original bytes are unchanged. Both public verification and Debt use this reader.

Real gate/prove producers cover all five public families: adaptive, exhaustive,
preservation assurance, test-only validation and no-op. Each verifies and feeds
`debt --certificate` without changing its bytes. Negatives cover corruption,
wrong candidate, malformed identities, unknown schema and contradictory bindings,
including contradictions added to otherwise rehashed test certificates.

Baseline: 10 failing subcases. Corrected targeted family and debt regressions PASS.
Full installed suite: 721 tests, 52 explicit skips, zero failures. Actual installed
Core plus the current private advisory wheel produce the same causal core; its
certificate verifies and feeds Debt with Private enabled and after disabling it.
This is not entitlement, native-client, HUMAN or release qualification.

Core wheel SHA-256: `e70e5a7fe7af1d0f5e4677135a99c98a32370579c6a32eee40c244f3ec0717a2`.
Raw logs are preserved losslessly in `PROOF_DEBT_BINDING/`.
Last-head review, hosted gates and fresh-main checks remain required.

## Exact-change base binding (review 4087849734)

Review found that the accepted candidate did not bind the measured base. Actual
A..C certificates fed to B..C fail the new regression in all five public families
on 2fd434f. Base and candidate now both bind their measured Git content. CLI debt,
Guard and repayment pass the resolved base; the shared scanner revalidates the
exact loaded certificate before any behavioral backing or proof signal is used.
This also prevents an unchecked alternate internal consumer from bypassing the
front-end validation. No certificate bytes or historical hashes are rewritten.

Two old accounting-only scanner fixtures used unbound fabricated IDs; they now
have valid base/candidate content hashes, while preserving the accounting asserts.
They remain unit fixtures, not evidence of a real proof producer. The independent
five-family subprocess tests exercise actual producer certificates. All wrong-base
cases refuse before writing the requested debt output and preserve the certificate.
46 accounting tests and all three five-family regression methods pass.
Updated installed-wheel full-suite evidence is recorded in base-review; skips are
preserved. New wheel SHA-256: `2419d79d9dee615edca8109cc3f346fb82410a6800aaf24135176397159a31fb`.

Full-suite integration found an omitted native-handoff call argument, then a
wrong variable name in the first correction. Both 10-failure runs remain in
base-review. The local-only targeted run also lacked the installed Idle entrypoint;
that failure and the corrected installed-environment run are retained. After
passing the actual captured base from native handoff, all 722 installed tests PASS
(52 explicit skips, 85.024 seconds). No native assertion was removed or skipped.
Final wheel SHA256 `e7515f3d9bec7cf2800339cc295c3bda612fdbec57a3e238591f6ec7ec69c0bd`.
