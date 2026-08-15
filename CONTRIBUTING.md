# Contributing

DiffWitness is intentionally small and deterministic. Contributions are welcome when they preserve the core property: evidence should come from reproducible execution, not from an opaque model score.

## Local checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Integration tests create real temporary Git repositories and detached worktrees. Git must be installed and a usable `python` command must be available to child test processes.

## Good contribution areas

- robust patch parsing for unusual Git diffs,
- inline-test overlays (Rust/Go/etc.),
- safe dependency-cache strategies,
- parallel execution without cross-mutant contamination,
- stronger minimization algorithms with explicit cost bounds,
- adapters that convert common CI test reports into multiple targeted witness commands.

Avoid adding an LLM dependency to the core verifier. Explanation layers can be optional; execution evidence should remain local and deterministic.
