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


## Qualify a source distribution

The sdist includes the source suite and the fixtures, schemas, hooks, scripts,
plugin manifests, Action and release-policy files that the suite exercises.
With Git and Python available, run:

```sh
python scripts/source_distribution_smoke.py dist/diffwitness-0.4.0a1.tar.gz --log source-suite.log
```

The harness extracts into a disposable directory outside the checkout, creates a
fresh virtual environment, installs the extracted source in editable mode and
runs the complete included unittest suite. Build dependencies must be available
to pip (downloaded or cached); optional syntax providers stay separate explicit
gates. The log retains every failure and skip. The JSON result binds the archive
and log hashes. In a Git checkout, add `--compare-source-root .` to require every
tracked test and fixture to match the archive byte for byte. This does not publish
an artifact, qualify a public tag or substitute for other release gates.
