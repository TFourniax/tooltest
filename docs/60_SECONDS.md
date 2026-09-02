# DiffWitness in 60 seconds

DiffWitness sits between **AI code generation** and **trust**. Native agent integration can run the proof boundary automatically; live Protect interception remains optional and independent.

## 1. Install and verify the command

During development from the repository:

```bash
pipx install .
pipx ensurepath
```

After `pipx ensurepath`, open a new shell (or reload your shell profile), then verify the executable before continuing:

```bash
command -v dw
dw --version
```

If `command -v dw` prints nothing on macOS/Linux/WSL, reload the current shell first, for example:

```bash
source ~/.bashrc
```

Then run `command -v dw` again. On Windows, open a new PowerShell/Terminal after `pipx ensurepath` and use:

```powershell
Get-Command dw
dw --version
```

A successful `pipx install` with an unavailable `dw` command is a PATH setup issue, not a failed DiffWitness installation.

After public release, install the published package or a pinned Git tag rather than tracking a moving branch.

## 2. Connect DiffWitness to the current Git project

Run these commands **inside the Git repository you want to use**:

```bash
dw setup --agent auto
dw setup status
```

`dw setup` installs only the detected/configured native integration scope. It does not silently enable Protect.

For Codex, configuration is not the same as provider trust: Codex must complete its own project/hook approval flow before DiffWitness can truthfully report a live Codex hook as observed. DiffWitness never self-approves that trust.

## 3. Check executable evidence readiness

```bash
dw doctor
```

If DiffWitness can safely detect an executable project check, it reports it. An explicit `.diffwitness.toml` always wins.

Example:

```toml
[diffwitness]
test = "pytest -q"
policy = "balanced"
strategy = "auto"
```

DiffWitness checks that the configured executable exists before calling verification `ready`. It does not silently rewrite a broken command.

## 4. Choose runtime protection — optional

Inspect the local agent/harness environment:

```bash
dw protect detect
```

Use DiffWitness builtin protection:

```bash
dw protect enable
```

Protect follows the project adapter scope established by `dw setup`. With current Codex builds, also complete Codex's own hooks/project-trust flow. After a live Codex hook reaches DiffWitness, `dw protect status` records that provider as observed.

Delegate live protection to an existing harness:

```bash
dw protect use external
```

Or keep live interception fully off:

```bash
dw protect disable
```

All three modes keep the same Proof, Debt Ledger, UNDERSTAND and Continuity semantics. Protect observations never become VERIFIED software behavior by themselves.

## 5A. Use Claude Code / Codex normally

Once `dw setup status` says the project integration and executable evidence are ready, open the configured coding agent normally:

```bash
claude
```

or:

```bash
codex
```

The native SessionStart boundary captures the starting repository state. The native Stop boundary evaluates the exact resulting change and connects PROVE · OWE · UNDERSTAND · CONTINUITY.

`dw guard` remains an explicit fallback when you intentionally want a process wrapper or when native integration is unavailable:

```bash
dw guard -- claude
```

## 5B. Protect a pull request

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

## 6. Inspect the current state

```bash
dw status
dw explain
dw health
dw ledger list
```

If the current worktree has drifted since an accepted Proof, `dw explain` scopes that Proof as historical/stale and tells you to re-verify. Returning exactly to the previously proved tree can make the exact content current again.

## 7. Verify or attach a certificate explicitly

```bash
dw verify evidence.json
```

A content change after proof makes the certificate stale. After committing the identical proved tree:

```bash
dw verify evidence.json --against HEAD
```

can remain valid because DiffWitness binds to Git tree content rather than requiring an ephemeral snapshot commit to survive.

Attach proof to Git history when desired:

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

- **I use Claude Code / Codex interactively:** `dw setup`, then use the agent normally.
- **I want live blocking/observation too:** `dw protect enable`.
- **I already use another runtime harness:** `dw protect use external`.
- **I do not want live interception:** `dw protect disable`.
- **I need an explicit process-wrapper boundary:** `dw guard`.
- **I own CI / branch protection:** `dw gate`.
- **I want maximum hunk detail:** `dw prove`.
- **My causal patch is huge:** `dw core` or Gate `strategy=auto`.
- **Someone sent me a certificate:** `dw verify`.

The important boundary is:

> optional runtime protection while the agent works, independent executable evidence on the exact change, persistent obligations and bounded human explanation afterward.

See [`PROTECT.md`](PROTECT.md) for the runtime protection contract.
