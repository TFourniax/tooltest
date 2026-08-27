# Debt Sensors

Debt Sensors are advisory, pluggable detectors that add maintenance-risk observations to Debt Ledger without participating in DiffWitness causal proof.

## Trust boundary

A sensor may report a heuristic finding, but it cannot change `WITNESSED`, `UNWITNESSED`, or `INCONCLUSIVE`, and it cannot fabricate a proof certificate. Sensor failures are non-blocking for the existing proof/debt path.

The first sensor is `semantic-redundancy-v1`. It looks for independently located code units with strongly overlapping normalized control/token structure, including common agent-generated reimplementations where function and local variable names changed. It uses only Python's standard library, runs locally, and does not export source code.

The finding is intentionally phrased as **possible semantic reimplementation**. Similarity is not functional equivalence and is never an instruction to delete or merge code.

## Accounting policy

Semantic redundancy findings are `heuristic`, category `redundancy`, and carry **0 points by default** during the calibration phase. They are still assigned stable `DW-...` identities and can be stored in Debt Ledger. This gives us real precision/false-positive data before allowing the sensor to affect debt budgets.

The first calibration ships enabled with conservative internal defaults: similarity threshold `0.85`, minimum unit size `32` normalized tokens, and at most `20` semantic-redundancy signals per scan. `max_scan_files` from the existing debt scanner still bounds repository work.

These calibration knobs are intentionally **not yet part of the public TOML contract**. Exposing thresholds before we have measured precision on a representative real-repository corpus would create a configuration surface we might later need to break. Once the sensor has benchmark evidence, the stable controls can be promoted through the normal validated DiffWitness configuration contract.

## Lifecycle

For a change, only code units touched by added lines are compared against the candidate repository. For project health, the sensor uses a banded SimHash candidate index before the more precise structural/vocabulary similarity calculation, avoiding an unconditional all-pairs scan.

Change and project modes deliberately use the same pair anchor and rule id, so a finding keeps the same Debt Ledger identity and can disappear naturally on a later project-rule recheck after a justified refactor.

## Extending

New sensors should implement the `DebtSensor` protocol and return `DebtSensorResult`. Their output must use `DebtSignal`, state the epistemic level honestly (`heuristic`, `deterministic`, etc.), and remain downstream of the proof engine.
