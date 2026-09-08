# Frozen human-qualified behavioral contract

Baseline core SHA: `e9bf514a3f13b1fc4124e3ff6a0e416016a2790b`.

Latest qualified main (2026-09-08): `4a53a9fd9f338b7deaa11ade26d02c933c86b6bf`.
HT005/HT012 readiness separation was merged through #56 after exact candidate machine qualification.
Exact-main SUCCESS: test `34220725034` (21/21 jobs), ProofBench `34220725026`,
ContinuityBench `34220725028`, Integrated Product Smoke `34220725017`.
Package artifact `10053625719`, SHA-256 `693f756dd66bf8da23c150b45d189eb35a1876152f6d4f1d40a353d0060be080`.
Closure/baseline record: issue #52 comment `5584489626`. Provider behavior, hook payloads,
trust interaction and executable resolution were unchanged; this presentation/state projection
correction did not require broad provider replay.

Previous qualified main: `bf10adb5fea60bba4b9d692411c6a56497092e12`.
HT009 was qualified and merged through #53. Installation-bound native/Protect hook resolution
was machine + Windows/Codex human qualified on `287c8c41a4eea3dd144e95bb95e011461bd7ec09`,
then merged through #55. Issue #54 retains the exact human evidence and closure record.
Post-merge SUCCESS: test `34198503601` (21/21 jobs), ProofBench `34198503623`,
ContinuityBench `34198503631`, Integrated Product Smoke `34198503607`.
The original baseline and behavioral evidence below remain historical records.

Canonical human evidence: [issue #52 and its comments](https://github.com/TFourniax/tooltest/issues/52). Claude native/manual Gate repairs: [PR #49](https://github.com/TFourniax/tooltest/pull/49). Claude Protect exec-form repair: [PR #50](https://github.com/TFourniax/tooltest/pull/50). Codex strict native stdout repair: [PR #51](https://github.com/TFourniax/tooltest/pull/51).

The source may evolve; these behaviors may not regress. Historical PASS does not qualify a later candidate automatically. Windows Codex evidence identifies CLI 0.153.2 and DiffWitness 0.4.0a1. Record exact Claude runtime versions from the original evidence before asserting version-specific support; do not invent one.

| Frozen behavior | Automated regression files | Human evidence / adapters |
| --- | --- | --- |
| Native setup merges foreign settings, no manual wrapper needed, task → Proof → Debt → Continuity | `test_native_setup_journeys.py`, `test_human_blocker_regressions.py`, `test_idleproof_sidecar.py` | #49/#51; Claude/Codex Windows |
| Claude lifecycle and Protect commands preserve Windows paths through exec form | `test_human_blocker_regressions.py`, `test_protect_claude_exec_hooks.py`, `test_native_hook_contracts.py` | #49/#50; Claude Windows |
| Codex Stop is one parseable provider JSON document, including real provider fields | `test_native_setup_journeys.py`, `test_native_hook_contracts.py` | #51; Codex Windows |
| Proof binds exact candidate tree; drift is stale; exact return restores applicability without a new Proof | `test_stale_proof_end_to_end.py`, `test_idleproof_freshness.py`, `test_continuity_reverification.py` | #52 Claude matrix and CP-05 |
| Manual Gate persists envelope, certificate and current state coherently | `test_human_blocker_regressions.py`, `test_gate.py` | #49 / HT-011 |
| Protect remains optional and separate from Proof; receipts bounded and integrity-valid | `test_protect.py`, `test_protect_ide_bridge.py`, `test_idleproof_protect_projection.py` | HT-017 and CP-01–05 |
| Destructive Git commands blocked before execution; sentinel survives, including global options `git -C . clean -fd[x]` | `test_protect_command_normalization.py`, `test_protect_destructive_end_to_end.py` | CP-02/CP-03 and Claude HT-017 |
| Codex-only setup stays Codex-only; disable removes only Protect; re-enable restores identical hooks and preserves provider trust | `test_protect.py`, `test_idleproof_sidecar.py` | CP-01/CP-04 |
| Protect and native Proof coexist after re-enable, with exact current coverage | `test_native_setup_journeys.py`, `test_protect_ide_bridge.py` | CP-05 |
| Guided/Technical preserve identical facts; LLM never creates authority | `test_view_mode.py`, `test_status_cli.py`, `test_idleproof_architecture_invariants.py` | Product trust doctrine; not a claim that existing localization is complete |

Test files are under `tests/`. The list indexes relevant coverage, not a substitute for executing it. HT-009 is an explicitly permitted correction to misleading readiness wording; persisted provider trust and conservative local observation must remain intact.

## High-risk change policy

Changes to hook generation, provider parsing, native handoff, destructive command normalization, Git identity, Proof/Continuity persistence or readiness require:

1. targeted regression tests;
2. full supported test suite;
3. `python benchmarks/proofbench.py`;
4. canonical `scripts/continuity_bench.py` gate;
5. `scripts/integrated_product_smoke.py` against the workflow's actual IdleProof revision;
6. applicable wheel/binary/Action consumer gates;
7. real provider/human requalification wherever runtime behavior or provider trust can differ.

Use the commands/thresholds in `.github/workflows/`, not invented replacements. Candidate qualification is tied to the exact SHA. Do not merge a changed human boundary on synthetic harness evidence alone. Re-run gates on exact main after a qualified merge. Never tag publicly while a reproducible P0/P1 remains.
