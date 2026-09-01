# Debt Sensors

Debt Sensors are advisory detectors downstream of DiffWitness Proof. They can observe maintenance, architecture and AI-generated-code risks, but they cannot mint, override or weaken a proof verdict.

## Trust boundary

A sensor finding is currently **heuristic / OBSERVED**, not VERIFIED. Sensor failures are isolated and fail open for that sensor only. The underlying DiffWitness proof and Debt Ledger accounting path continues unchanged.

Current sensor findings intentionally carry **0 debt points** while precision is benchmarked on real repositories. They may be persisted as inspectable obligations, but they cannot make an otherwise passing debt budget fail during this calibration phase.

## Implemented sensors

### `semantic-redundancy-v1`

Looks for structurally similar reimplementations that are not exact source copies. It uses local deterministic token normalization, SimHash candidate retrieval and bounded exact scoring. No embedding API, hosted model or external service is required. Exact source copies remain owned by the existing deterministic duplicate detector.

### `parallel-source-of-truth-v1`

Looks for a domain constant/value concept that becomes independently declared in multiple production files. Change mode compares base and candidate trees and only reports a group when the candidate increases the number of files carrying that same normalized concept/value pair. Values are fingerprinted in evidence rather than exported verbatim.

This is deliberately conservative: it targets explicit constant declarations, not every repeated literal or object property.

### `duplicate-security-policy-v1`

Derives a security-specific observation from an existing semantic-redundancy result when the matched locations are security-sensitive (authorization, permissions, tenant isolation, tokens, sessions, validation, webhooks, policies, and related contexts). It **reuses** the semantic scan instead of scanning the repository a second time.

A finding means “possible policy divergence risk”, not “vulnerability found”.

### `agent-expansion-v1`

Change-scoped breadth detector for unusually large structural expansion: many production files, large added-line surface, structural/new-file growth, and new declarations in one change. It does not infer that the user asked for a simple task and does not claim that a large change is wrong. It asks whether the breadth was intentional and whether the same intended behavior could be delivered with a smaller surface.

### `layer-bypass-v1`

Change-scoped architecture detector. It only reports a new presentation -> persistence local import when the **same source file historically depended on a service/application mediator**. This deliberately avoids declaring every direct database import a violation.

The finding means that a previously visible architectural path may now be bypassed. It does not prove that validation, authorization, transactions or domain policy were actually skipped.

### `parallel-abstraction-v1`

Derives from high-confidence (`>= 0.92`) semantic-redundancy pairs when both locations look like architectural abstractions (service, manager, client, repository, store, provider, gateway, adapter, controller, handler, coordinator, engine, registry or factory).

It reuses semantic evidence rather than performing another similarity scan. A finding asks whether two abstraction entry points now own the same responsibility; it does not require consolidation.

### `dependency-sprawl-v1`

Looks for a newly added direct production dependency when the same package scope already carries another direct dependency from a conservative overlapping family such as HTTP clients, date/time libraries, validation libraries or logging libraries.

Change mode requires a **new overlap** relative to the base tree. Project mode can surface an existing overlap. Package scope and ecosystem are part of the identity, so unrelated monorepo packages are not grouped together.

The curated family list is intentionally narrow. DiffWitness does not infer overlap between arbitrary packages.

### `orphan-code-v1`

Change-scoped migration-residue detector over the local static import graph. It reports an unchanged production module when:

- it had local importers in the base tree;
- it has no local importers in the candidate;
- at least one former importer changed in the current diff;
- the target module itself was left unchanged; and
- it is either a service/persistence module or had multiple prior importers.

Dynamic imports, framework discovery, reflection, plugin registration and external consumers are explicitly outside this observation. A finding is therefore a removal-review candidate, never a deletion order.

## Shared discovery and cost control

Sensors reuse discovery work where possible:

- `duplicate-security-policy-v1` and `parallel-abstraction-v1` derive from the semantic-redundancy result;
- `layer-bypass-v1` and `orphan-code-v1` share one bounded local import-graph pass;
- `agent-expansion-v1` reads only the Git diff;
- `dependency-sprawl-v1` reads supported direct-dependency manifests only.

This keeps the sensor layer additive without turning every protected change into several independent whole-repository scans.

## Calibration defaults

The sensor tuning values are internal alpha calibration defaults. They are intentionally not part of the stable public TOML configuration contract yet. Public configuration will be promoted only after a labeled precision corpus demonstrates that the controls are useful and stable.

All sensors must preserve:

- local-first source inspection;
- no raw source export in sensor evidence;
- stable, inspectable Debt Ledger identities where applicable;
- zero authority over DiffWitness causal proof;
- independent failure isolation;
- high precision over warning volume.

Before any sensor receives non-zero debt points, it must earn that authority through a labeled SensorBench corpus with hard-negative cases from real AI-assisted repositories.
