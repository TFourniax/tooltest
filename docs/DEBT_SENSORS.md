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

## Calibration defaults

The sensor tuning values are internal alpha calibration defaults. They are intentionally not part of the stable public TOML configuration contract yet. Public configuration will be promoted only after a labeled precision corpus demonstrates that the controls are useful and stable.

All sensors must preserve:

- local-first source inspection;
- no raw source export in sensor evidence;
- stable, inspectable Debt Ledger identities where applicable;
- zero authority over DiffWitness causal proof;
- independent failure isolation;
- high precision over warning volume.

Future approved sensor families include layer bypass, parallel abstractions, dependency sprawl and orphan-code/migration residue. They should enter through the same advisory contract and earn stronger accounting semantics only after benchmark evidence.
