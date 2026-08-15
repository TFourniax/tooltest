# Contributing

DiffWitness is deliberately small and standard-library-first. Contributions should preserve the ability to run the core engine without a hosted service or paid dependency.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

The integration suite creates real temporary Git repositories and exercises worktree snapshots, test overlay, reverse hunk ablation, sufficient-subset search and interaction detection.

## Design rules

- Prefer explicit `inconclusive` states to false certainty.
- Never mutate the user's real Git index as part of analysis.
- Keep core analysis language-agnostic; language-specific adapters may improve ergonomics but should not be required.
- A new causal label needs a clear counterfactual definition and an integration test.
- Search budgets must be bounded; exact combinatorial work should never appear accidentally on a large patch.
- Do not silently weaken evidence because a command is expensive or flaky.

## Before a PR

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps
```
