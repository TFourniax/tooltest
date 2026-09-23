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
