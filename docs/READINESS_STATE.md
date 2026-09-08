# HT005 / HT012 — readiness contract

Baseline reproduced before implementation: `bf10adb5fea60bba4b9d692411c6a56497092e12`. Exact status/doctor/setup JSON and human outputs (temporary paths normalized) are in `qualification/ht005-ht012-before.json`. HT005 removes native hooks after a real setup; HT012 retains fresh hooks without a provider invocation. Both report native ready from scope alone. The two findings share a projection defect, not a provider-runtime defect.

## Facts and truth table (defined before coding)

Readiness is a local, non-executing preflight. It never runs evidence, approves providers, installs hooks or records observation. Native facts come from the existing scope/integration records, existing owned-hook signature checks, the recorded executable path and native activation store. No PATH-based replacement executable is selected while inspecting status. A previous observation remains historical even if a hook/executable subsequently disappears.

| Configuration | Owned hooks | Recorded executable | Observed | Runtime usable locally | Required action |
|---|---|---|---|---|---|
| absent | absent | unknown | absent | false | configure native integration if wanted |
| present | absent/broken | any | either | false | repair installation |
| present | present | unavailable | either | false | repair recorded installation |
| present | present | available | false | false | observe a harmless provider invocation |
| present | present | available | true | true | none for this local hook preflight |

Codex providerTrust stays `unknown` in every row. Claude/Cursor retain `not-required` as in the frozen native activation contract. Observed never means approval is permanent. Lack of observation never means approval is required. Local runtime usability is bounded to installation + executable presence + recorded observation, not a guarantee the provider will run a future hook.

Verification has independent `configured`, `selected`, `executableReady` and `ready` facts. Detected evidence can be executable without explicit configuration. Executable means the launcher is available; tests have not been run and their outcome is unknown. Use the same existing conservative default-evidence selection everywhere.

Protect remains separately scoped: off is optional/unselected; external is delegated with local readiness unknown; builtin requires installed/ready adapter facts and valid receipt integrity. Protect readiness never establishes Proof.

Current-tree verification and freshness reuse the existing status exact-tree projection without modifying its evidence or Git identity rules. An accepted historical Proof on a different tree is stale, even if every installation preflight is ready. A clean tree alone is not proof.

The selected local readiness scope covers verification-launcher preflight, configured native hooks when selected, and builtin Protect when selected. It explicitly excludes provider approval, test outcomes, current-tree Proof, remote services and optional planner capability/Continuity health. Doctor additionally reports its existing engine/Continuity checks. There is no universal product-ready boolean that hides these scopes.

## Compatibility and consumers

Add a versioned `readiness` object to status/setup/doctor while preserving their top-level v1 schemas and existing field names. Correct the buggy `setup.native_ready` and `doctor.native.ready` aliases to mean the explicitly reported native runtime usability; add native configured/installed fields. Correct setup `productReady` to the explicitly named selected-local scope and document `productReadyScope`. These are pre-release bug corrections, not silent reinterpretations: clients needing the old configuration fact must use the new configured field. Doctor's ready/exit code includes its existing engine/Continuity preflight plus the selected local scope. Setup installation success remains distinct from readiness and still succeeds before first observation. Setup JSON status remains an inspection operation with its established successful-read exit behavior.

Status/doctor/setup human views and next actions consume the same facts. Missing installation recommends repair; installed/unobserved recommends observation with conditional provider review guidance; normal native work is recommended only when locally usable. Continuity guidance must not turn a scope record alone into a claim that Stop will run. Guided and Technical share the projection; localization remains a later separate phase.

Inspected consumers: status_cli, setup, doctor, native_activation, Protect status, bundled idleproof_entry/idleproof_sidecar, continuity_context_enriched; unit/native journeys and package/consumer scripts. External sidecar does not consume the corrected CLI fields. The Portal snapshot is a separate bounded schema and receives no readiness extension in this phase. Indexed remote searches were incomplete and are not used as evidence of absence.

No hook generator, provider handler, trust store, executable resolver or Proof writer changes are permitted in this correction. Full machine gates and exact diff inspection determine whether any new human boundary exists.
