# DiffWitness ProofBench

ProofBench is a small reproducible benchmark for the semantic failures DiffWitness is designed to surface.

Run it from an installed development checkout:

```bash
python benchmarks/proofbench.py
```

or machine-readable:

```bash
python benchmarks/proofbench.py --json
```

Current scenarios intentionally compare a naive "candidate test command is green" decision with the richer DiffWitness evidence category:

1. **Scope creep hidden by green tests** — the real bugfix is covered, an unrelated second production hunk is not. Naive CI is green; strict DiffWitness rejects the patch.
2. **Non-discriminating new tests** — candidate tests pass, but they also pass when overlaid onto the old production code. Naive CI is green; balanced DiffWitness rejects the evidence as non-discriminating.
3. **Behavior-preserving refactor** — the same existing evidence is stably green on base and candidate, with no changed test surface. DiffWitness records preservation assurance rather than incorrectly demanding repair-style hunk necessity.
4. **Documentation-only change** — DiffWitness emits a formal proof-not-required certificate instead of manufacturing a test-based causal claim.

ProofBench is not meant to make DiffWitness look good by counting synthetic successes. Its purpose is to pin down semantics that can regress as the engine evolves. New scenarios should represent a concrete trust failure and state exactly which claim DiffWitness is allowed to make.

Future benchmark tracks should include real-world agent patches collected from public repositories, anonymized false-positive reports, flaky CI fixtures, dependency/build changes, and large multi-hunk repairs where Adaptive Core materially reduces experiment count.
