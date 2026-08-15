# DiffWitness in 60 seconds

DiffWitness is designed to sit between **code generation** and **trust**.

## 1. Install

During development from the repository:

```bash
pipx install .
```

After public release, install the published package or a pinned Git tag rather than tracking a moving branch.

## 2. See what evidence DiffWitness would use

```bash
dw doctor
```

If the suggested command is right, continue. If not, make the evidence explicit once:

```toml
[diffwitness]
test = "pytest -q"
policy = "balanced"
strategy = "auto"
```

## 3A. Using a coding agent locally

Keep your normal workflow:

```bash
dw guard -- claude
```

or:

```bash
dw guard -- codex
```

The agent remains interactive. DiffWitness captures repository state before and after, then sends the exact produced diff through the same Gate used by CI.

## 3B. Protect a pull request

```bash
dw gate --base origin/main --candidate HEAD
```

Default semantics:

```text
docs-only                  -> proof-not-required
changed tests, no prod     -> validation-only
base PASS, candidate PASS  -> preservation assurance
changed tests pass on base -> non-discriminating evidence
base FAIL, candidate PASS  -> causal proof
small causal patch         -> exhaustive real-hunk analysis
large causal patch         -> budgeted Adaptive Core
```

No confidence score hides these categories.

## 4. Verify that a proof still belongs to the code

```bash
dw verify evidence.json
```

A content change after proof makes the certificate stale.

After committing the identical proved tree:

```bash
dw verify evidence.json --against HEAD
```

can remain valid because DiffWitness binds to Git tree content rather than requiring an ephemeral snapshot commit to survive.

## 5. Attach proof to Git history

```bash
dw note evidence.json --commit HEAD
git push origin refs/notes/diffwitness
```

The note does not rewrite the commit SHA.

## GitHub Action

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- uses: TFourniax/tooltest@main
  with:
    base: ${{ github.event.pull_request.base.sha }}
    candidate: ${{ github.event.pull_request.head.sha }}
```

Once public releases exist, pin a release tag or immutable commit instead of `main`.

## What to choose

- **I use Claude Code / Codex:** `dw guard`.
- **I own CI / branch protection:** `dw gate`.
- **I want maximum hunk detail:** `dw prove`.
- **My causal patch is huge:** `dw core` or Gate `strategy=auto`.
- **Someone sent me a certificate:** `dw verify`.

The important habit is not the command. It is the boundary:

> generation first, independent executable evidence second.
