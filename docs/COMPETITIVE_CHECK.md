# Late-stage competitive check — 2026-08-15

A final competitor sweep after the first DiffWitness prototype surfaced **idpcom/causal-repair**, a July 2026 repair harness built around proof-carrying witnesses. It is philosophically close enough that it deserved a direct mechanism-level comparison before making any novelty claim.

## What causal-repair does

Its `scripts/verify-coverage.py` computes a **function-level change surface** by running deterministic differential inputs against base and patched code. It then requires the broken/at-risk contract witnesses to exercise every function whose observable behavior changed.

Source: https://github.com/idpcom/causal-repair/blob/main/scripts/verify-coverage.py

Its `scripts/mutate.py` creates deterministic **synthetic AST mutants** of Python code (for example comparison flips, integer nudges, removed `raise` statements and boolean-operator flips) so contract witnesses can demonstrate mutation strength.

Source: https://github.com/idpcom/causal-repair/blob/main/scripts/mutate.py

## Why DiffWitness is still a different primitive

The two projects share the thesis that a green test result is insufficient evidence by itself, but they ask different counterfactual questions:

- **causal-repair:** does every behavior-changed function have an appropriate contract witness, and are those witnesses strong against generated mutants?
- **DiffWitness:** for every **actual hunk in this proposed Git diff**, does removing that exact hunk make the selected evidence stop being green?

DiffWitness therefore treats the submitted patch itself as the mutation surface. It automatically reverse-applies each real production hunk, reruns the user's test command, and emits a hunk→evidence witness map. Its core mechanism is language-agnostic: Git must be able to apply the diff and the repository must expose a runnable test command.

That distinction matters in review. Function coverage can show that a witness visited a behavior-changing function without showing that every proposed edit inside the patch was necessary for the asserted result. Conversely, hunk ablation can identify a scope-creep/refactor hunk that the chosen evidence does not require even when that hunk lives inside a function that is otherwise exercised.

## Novelty statement

The claim remains deliberately narrow: **in the web/GitHub sweep performed on 2026-08-15, no general-purpose free tool was found that combines candidate-test overlay onto the base, automatic reverse ablation of each actual production Git hunk, a hunk-level witness map, and optional greedy patch minimization.**

This is a research result, not a patent-style claim that no private, unpublished, differently named, or unindexed implementation exists.
