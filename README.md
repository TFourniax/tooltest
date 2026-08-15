# DiffWitness

> **Green is not proof. A passing test should be able to witness the change it claims to validate.**

DiffWitness is a zero-runtime-dependency CLI that asks a question most test pipelines never ask:

**Which exact parts of this Git diff are actually necessary for the selected tests to stay green?**

It takes a base revision and a candidate patch, runs the chosen test command, then creates counterfactual versions of the candidate with each production hunk removed one at a time.

- If removing a hunk makes the tests fail, that hunk is **WITNESSED**.
- If the tests still pass, that hunk is **UNWITNESSED** by this test command.
- If the counterfactual cannot be constructed reliably, it is **INCONCLUSIVE**.

This is deliberately different from line coverage. Coverage asks *“did a test execute this line?”* DiffWitness asks *“would the evidence still be green if this change had never been made?”*

## Why this exists

AI coding agents have made patches faster to produce than they are to verify. The usual final signal is still some version of:

```text
Tests: 128 passed ✅
```

But a green test can be irrelevant to the claimed fix. A July 2026 study of validation events in LLM repair agents found that **46% of positive comparable validation events carried no bug-discriminating information**: they were green, but did not establish the claimed repair against the buggy state.

DiffWitness turns verification into a counterfactual question at **hunk granularity**, not just patch granularity.

## The core idea

```text
                           selected test command
                                   │
                     ┌─────────────┴─────────────┐
                     │                           │
              base + new tests               candidate
                 should fail                  must pass
                     │                           │
                     └─────────────┬─────────────┘
                                   │
                         candidate is green
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
          remove hunk A        remove hunk B        remove hunk C
              │                    │                    │
          tests fail            tests pass           tests fail
              │                    │                    │
          WITNESSED           UNWITNESSED          WITNESSED
```

A useful side effect: the unwitnessed set is a high-signal place to look for agent scope creep, bonus refactors, dead changes, or missing regression tests.

## Quick start

Requires Python 3.11+ and Git.

```bash
pipx install .
# or
python -m pip install .
```

From a repository with an agent's current uncommitted changes:

```bash
diffwitness prove \
  --base HEAD \
  --candidate WORKTREE \
  --test "python -m pytest -q"
```

`WORKTREE` is special: DiffWitness snapshots staged, unstaged, and non-ignored untracked files using an **alternate Git index**. It does not rewrite your real index or working tree.

For a committed branch:

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "npm test"
```

### Example output

```text
DiffWitness — counterfactual patch evidence
base:      HEAD (1ad1c5d53a13)
candidate: WORKTREE (676c091d0b40)
test:      python -m unittest discover -s tests -q
changes:   2 production mutation(s); 1 changed test file(s)

contrast:  BASE FAIL → CANDIDATE PASS  [bug-discriminating command]

WITNESSED     c31290c4d8    +1/-1  calc.py hunk 1/2 — def add(a, b):
UNWITNESSED   0d33715f1a    +1/-1  calc.py hunk 2/2 — def label():

witness map: 1/2 conclusive changes are necessary for this test command to stay green
```

## A detail that matters: new tests are replayed on the old code

A common bug-fix patch adds both production code and a new regression test. If you simply check out the base revision, that new test disappears — and a baseline run can become meaningless.

By default DiffWitness detects changed test files and overlays **candidate-side test changes onto the base** before running the baseline command:

```text
base code + candidate regression tests → expected FAIL
candidate code + candidate tests        → expected PASS
```

Test changes are excluded from hunk-ablation analysis by default. The goal is to ask whether the **production changes** are witnessed by the tests, not whether deleting the tests makes the suite easier to pass.

Add project-specific test locations with:

```bash
diffwitness prove ... --test-glob "qa/**/*.py" --test-glob "checks/**"
```

Or disable the overlay for projects with inline tests:

```bash
diffwitness prove ... --no-test-overlay
```

## Greedy patch minimization

DiffWitness can go one step further and search for a smaller version of the candidate that still passes the selected test command:

```bash
diffwitness prove \
  --base origin/main \
  --candidate HEAD \
  --test "pytest tests/test_checkout.py -q" \
  --minimize \
  --reduction-patch /tmp/remove-surplus.patch
```

The minimizer removes candidate mutations one by one and keeps a removal only while the tests stay green. The result is a **local/greedy minimum**, not a mathematical guarantee of the globally smallest patch; removal order can matter.

DiffWitness never applies the reduction to your source repository. It only writes the patch if you explicitly request it.

## CI gates

The default command reports evidence but does not treat an unwitnessed hunk as an error — because an unwitnessed change can be legitimate behavior outside the selected test command.

For stricter workflows:

```bash
# Fail if the chosen command is already green on the base.
diffwitness prove ... --require-contrast

# Fail if any conclusive production mutation is unwitnessed.
diffwitness prove ... --require-all-witnessed
```

Reports:

```bash
diffwitness prove ... \
  --json .diffwitness-report.json \
  --report .diffwitness-report.md
```

Exit codes:

- `0` analysis completed and requested gates passed
- `2` setup, Git, candidate-test, or analysis error
- `3` `--require-contrast` failed
- `4` `--require-all-witnessed` failed

## Keeping dependency setup practical

Each state is tested in a disposable Git worktree, so your source checkout is not used as a test sandbox.

If setup is required:

```bash
diffwitness prove ... \
  --prepare "npm ci" \
  --test "npm test"
```

For large local dependency folders you can explicitly share a path into the sandbox:

```bash
diffwitness prove ... \
  --share node_modules \
  --test "npm test"
```

**Warning:** a shared path is a symlink to the original path. A test or script can therefore mutate that shared target. Use `--prepare` instead when strict isolation matters more than speed.

When a root `node_modules` exists, DiffWitness also exposes its `.bin` directory on `PATH` and sets `NODE_PATH` for the sandbox process; this is a convenience, not a guarantee for every Node module-resolution mode.

## What DiffWitness is — and is not

DiffWitness provides **counterfactual evidence**, not formal correctness proof.

A `WITNESSED` hunk means removing that hunk caused the selected command to fail. It may be necessary because of behavior, compilation, imports, or interactions with another hunk.

An `UNWITNESSED` hunk means the selected command stayed green without it. That can indicate:

- unrelated scope creep,
- a valid change with no relevant regression test,
- a redundant implementation path,
- documentation or cleanup intentionally outside the test's concern,
- or an alternative fix where another hunk can compensate.

That distinction is why DiffWitness reports evidence instead of pretending to produce a universal “safe/unsafe” score.

## How it stays out of your way

For `WORKTREE`, DiffWitness creates an ephemeral Git commit with an alternate index. It then uses disposable detached worktrees for all execution and cleans them up afterward.

It does **not** intentionally modify:

- your working-tree files,
- your staging index,
- your branch refs,
- your commits.

Git necessarily creates temporary objects/worktree metadata while the analysis runs; unreachable snapshot objects are eligible for normal Git garbage collection later.

The test command is supplied by you and runs with your user permissions inside the disposable worktree. Read [SECURITY.md](SECURITY.md) before using untrusted commands or repositories.

## Research / competitive landscape

The idea was selected after rejecting several initially attractive directions that were already crowded: cross-LLM memory, agent command guards, local CI debuggers, environment diffing, and global patch proof tools.

The closest adjacent work we found does **different jobs**:

- **BSG-VA (Xu & Wu, 2026)** measures whether agent validation commands discriminate buggy/candidate/gold states and reports a large evidence-quality gap.
- **PatchProof** checks the important global property “changed regression test fails on base, passes on patch.”
- **AdaptOrch CEK** treats base-fail / patch-pass as strong patch evidence in a larger verification control plane.
- **ChaCo** targets *coverage* of PR-modified lines by generating tests.
- Traditional **mutation testing** mutates the program to assess test-suite strength; DiffWitness instead ablates the *actual proposed patch* to ask which candidate edits have a witness.

As of **2026-08-15**, our web/GitHub research did not surface a general-purpose free tool with this exact workflow: candidate-test overlay on base + automatic per-hunk counterfactual ablation + a hunk-level witness map + optional candidate minimization. That is a research finding, not a patent-style claim that no implementation can exist anywhere.

See [docs/RESEARCH.md](docs/RESEARCH.md) for sources and rejected ideas.

## Development

No runtime dependencies.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The integration suite creates real temporary Git repositories/worktrees and verifies that DiffWitness can distinguish a bug-fixing hunk from an unrelated hunk while a newly-created, untracked regression test is overlaid onto the base.

## License

MIT.
