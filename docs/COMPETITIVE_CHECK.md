# Competitive / prior-art check

Last checked: 2026-08-15.

The novelty claim for DiffWitness is intentionally narrow. Many mature tools already exist for mutation testing, coverage, test selection, repair validation, flaky-test detection, patch minimization, and coding-agent harnesses. DiffWitness should be judged on the **combination and developer-facing primitive**, not on a claim to have invented counterfactual testing.

## Closest public project found: causal-repair

A late-stage GitHub search surfaced `idpcom/causal-repair`, a July 2026 repair harness built around proof-carrying witnesses.

Repository: https://github.com/idpcom/causal-repair

Its `scripts/verify-coverage.py` computes a function-level behavioral change surface using deterministic differential inputs, then requires broken/at-risk contract witnesses to exercise every behavior-changed function.

Its `scripts/mutate.py` produces synthetic AST mutants such as comparison flips, integer nudges, removed `raise` statements, and boolean-operator flips to evaluate witness strength.

DiffWitness shares the thesis that “tests passed” is insufficient evidence, but its core primitive differs:

- **causal-repair:** identify behavior-changed functions and require appropriate contract witness coverage; challenge witnesses with generated mutants.
- **DiffWitness:** treat each **actual submitted Git hunk** as the intervention. Reverse-ablate real hunks for necessity, build real-hunk subsets from base for sufficiency, detect mutual-backup interactions, and require stable repeated outcomes before making causal labels.

Function-level witness coverage can show that a changed function was exercised without proving every proposed edit in that function mattered. Conversely, hunk ablation can surface refactor/scope-creep edits even when they live inside a function the test visits.

## Adjacent categories

### Mutation testing

Tools such as PIT, Stryker and mutmut synthesize code mutations and measure whether tests kill them. DiffWitness borrows the experimental mindset but uses the real candidate patch as its primary intervention surface.

### Patch coverage / test augmentation

ChaCo targets PR-modified lines not covered by tests and generates new tests. DiffWitness consumes a chosen evidence command and asks causal questions about the submitted diff. These are complementary.

### Delta debugging / patch minimization

Delta debugging and reducer tools search for smaller failure-inducing or behavior-preserving inputs/patches. DiffWitness v0.2 includes a deliberately modest greedy reduction, but its main artifact is a reviewable witness/sufficiency map rather than only a minimized patch.

### Flaky-test products

Flaky-test tooling detects unstable tests/builds from repeated or historical outcomes. DiffWitness does not aim to become a flaky-test management platform; it uses repetition locally so unstable evidence cannot silently become a causal label.

## Narrow novelty statement

In the public web/GitHub sweep performed through 2026-08-15, no general-purpose free tool was found that combines all of the following as one Git/CI workflow:

1. candidate-test overlay onto the base;
2. automatic reverse ablation of each **actual production Git hunk**;
3. repeated-run stability classification before assigning causal labels;
4. forward search for minimal-cardinality **real-hunk sufficient subsets**;
5. interaction search for mutually backing-up unwitnessed hunks;
6. a hunk-level machine-readable evidence certificate and native GitHub annotations;
7. optional local patch reduction.

This is a search result, not a patent-style assertion. A private, unpublished, unindexed, differently named, or newly released implementation may exist.
