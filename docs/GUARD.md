# DiffWitness Guard

`dw guard` is the explicit fallback that turns any coding-agent process into a proof-carrying code
session when native integration is unavailable or when a user deliberately wants a process-owned
boundary. For normal Claude Code or Codex use, run `dw setup` once and then launch the provider
normally.

```bash
dw guard -- claude
dw guard -- codex
```

The terminal remains interactive. DiffWitness captures an immutable Git snapshot before the child process starts, then captures the final repository state after it exits and proves the exact resulting diff.

## Guard vs Protect

Guard and Protect solve different problems.

```text
Protect   optional live runtime guardrails while a supported agent works
Guard     stable before/after process boundary
Proof     executable evidence over the resulting exact Git change
Debt      persistent obligations discovered from the change/evidence
```

Protect can be builtin, delegated to another harness, or off:

```bash
dw protect enable
dw protect use external
dw protect disable
```

None of these choices changes Guard's post-change proof semantics.

See [`PROTECT.md`](PROTECT.md).

## Why wrap the process?

Lifecycle hooks are convenient but belong to the agent runtime. A wrapper belongs to the user's shell and therefore gives DiffWitness a stable before/after boundary even if the agent:

- creates commits;
- stages or unstages files;
- creates untracked regression tests;
- changes branches inside the repository;
- does not expose a reliable Stop hook.

Guard does not intercept the agent's prompts, model output, or source-code contents. It observes the Git artifact before and after the process.

## Zero-config evidence

When `--test` is omitted, Guard looks for explicit project signals, in order, such as:

- package-manager `test` scripts;
- pytest configuration/dependency markers;
- Python `tests/` fallback to `unittest`;
- Cargo;
- Go modules;
- Maven;
- Gradle;
- Composer;
- RSpec.

Inspect the plan without running anything:

```bash
dw doctor
```

Explicit project configuration always wins:

```toml
[diffwitness]
test = "pytest -q"
stability_runs = 2
```

## Policies

Guard proof policy is separate from Protect runtime policy.

### Balanced — default

```bash
dw guard --policy balanced -- claude
```

Rejects unstable/inconclusive proof and strong surplus candidates. It does not require every hunk to be individually necessary because legitimate changes can implement requirements outside one selected evidence command.

### Strict

```bash
dw guard --policy strict -- codex
```

Requires stable base-fail -> candidate-pass contrast and no unwitnessed/inconclusive analyzed production hunk.

Use this for narrow bug-fix tasks with a strong regression test.

### Observe

```bash
dw guard --policy observe -- claude
```

Never blocks on evidence policy. Useful while introducing DiffWitness to a repository and learning what the existing suite actually proves.

These names intentionally resemble Protect's `observe / standard / strict` vocabulary, but the policies act on different boundaries. `dw guard --policy strict` is a **proof acceptance policy**; `dw protect enable --policy strict` is a **runtime action policy**.

## Certificates

Preserve the evidence:

```bash
dw guard \
  --certificate .diffwitness/last-proof.json \
  -- claude
```

The certificate is independent of the agent or harness that created the change.

## Plugins

The repository also contains Claude Code and Codex plugin manifests plus lifecycle hooks. When the runtime loads them, DiffWitness captures state at `SessionStart` and evaluates the final patch at `Stop`.

Builtin Protect, when explicitly enabled, installs separate `PreToolUse` / `PostToolUse` hooks into supported local agent configuration. Protect uninstall removes only DiffWitness-managed runtime hooks and preserves unrelated hooks.

The plugin can ask the agent to continue when proof is rejected. To prevent pathological loops, the current hook gate caps automatic continuation attempts and then surfaces the unresolved proof instead of trapping the session indefinitely.

Guard remains the deliberate fallback when you require a guaranteed process boundary. Never ask an
already-running Claude Code or Codex session to launch Guard: that would create a nested agent.

## Important limitation

Guard can only prove what the selected executable evidence expresses. Passing DiffWitness is not a mathematical proof of software correctness and is not a replacement for security review, integration testing, or requirements engineering.

Likewise, a Protect block is a runtime safety observation, not proof that the final software is correct.
