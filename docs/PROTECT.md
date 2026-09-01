# DiffWitness Protect

Protect is an **optional local runtime guard layer** for AI coding agents. It runs before or immediately after supported agent tools, while DiffWitness Proof remains the independent post-change evidence boundary.

The design rule is simple:

```text
Protect controls risky actions while the agent works.
Proof establishes what executable evidence says about the resulting Git change.
Debt keeps unresolved engineering obligations alive.
IdleProof explains those signals without upgrading them.
```

Protect is not required to use DiffWitness. `dw guard`, `dw gate`, proof certificates, Debt Ledger and IdleProof continue to work when Protect is disabled or delegated to another harness.

## Modes

### Builtin

```bash
dw protect enable
```

or explicitly:

```bash
dw protect use builtin
```

DiffWitness installs only its own `PreToolUse` / `PostToolUse` hooks into supported local agent configuration and preserves unrelated hooks.

Current builtin adapters in this alpha:

- Claude Code;
- Codex.

#### Codex activation and trust

Current Codex builds keep lifecycle hooks behind Codex-owned feature and trust boundaries. `dw protect enable` installs DiffWitness's project hook configuration, but DiffWitness deliberately does **not** grant itself Codex trust.

For Codex builtin Protect, complete Codex's own flow:

1. enable Codex's `hooks` feature (for example, `codex --enable hooks`, or the equivalent user-owned Codex configuration);
2. accept Codex's normal project-trust decision for the repository;
3. review and approve the DiffWitness hooks in Codex's `/hooks` surface;
4. let Codex invoke a tool, then check `dw protect status`.

Until a live trusted Codex hook actually invokes DiffWitness, the Codex adapter remains conservatively not-ready rather than claiming protection that has not run. DiffWitness never writes Codex project trust, never writes a trusted hook hash on the user's behalf, and never uses Codex's dangerous hook-trust bypass in product code.

### External

```bash
dw protect use external
```

Use this when another harness already owns live runtime safety. DiffWitness does not install its Protect hooks, but Proof, Debt, Continuity and IdleProof remain available.

### Off

```bash
dw protect disable
```

or:

```bash
dw protect use off
```

Off means **no DiffWitness Protect interception**. Protect hooks managed by DiffWitness are removed while unrelated hooks are preserved.

## Detection

Inspect the local environment before choosing a mode:

```bash
dw protect detect
```

DiffWitness looks for high-confidence local harness signals and existing agent hook activity.

- A high-confidence external-harness signal makes `builtin` delegate to `external` by default.
- Existing foreign hooks without a high-confidence harness marker do not automatically disable builtin Protect; installation merges non-destructively.
- `--force` is required to install builtin Protect despite a high-confidence external harness signal.

Example:

```bash
dw protect enable --force
```

`dw setup` may recommend a mode, but it does not silently enable Protect.

## Policies

Protect has three runtime policies.

### `standard` — default

```bash
dw protect enable --policy standard
```

High-confidence dangerous actions are blocked. Dependency installation is observed but not interrupted.

### `strict`

```bash
dw protect enable --policy strict
```

High-confidence dangerous actions are blocked. Dependency-install requests ask for confirmation when the provider hook protocol safely supports that decision. Current Codex `PreToolUse` rejects `ask`, so strict Protect blocks that dependency-install action instead of silently downgrading the policy.

### `observe`

```bash
dw protect enable --policy observe
```

Findings are recorded but Protect does not block them. This is useful when introducing runtime protection to an existing workflow.

## Current deterministic protections

The alpha intentionally starts with a bounded, high-confidence rule set rather than hundreds of speculative rules. Current checks include:

- destructive Git operations such as hard reset, force push, forced clean and forced branch/worktree removal;
- broad recursive filesystem deletion patterns;
- direct writes outside the active repository;
- direct agent writes into `.git` metadata;
- remote-download pipe-to-shell patterns;
- destructive database/schema drop commands;
- several high-confidence credential/private-key patterns in proposed or landed text;
- dependency installation observation / confirmation according to policy;
- post-edit JSON syntax checks;
- post-edit Python syntax checks.

A clean action is **not force-allowed by DiffWitness**. Protect stays silent and the coding agent's own permission system remains authoritative.

## Receipts

Inspect bounded runtime observations:

```bash
dw protect log
```

or:

```bash
dw protect log --json
```

Local receipts are stored under Git metadata and hash-linked. They contain bounded metadata such as decision class, rule/category, provider/tool label and repository-relative path when available.

They do **not** intentionally store:

- raw commands;
- source-file contents;
- raw prompts;
- raw agent-event streams;
- raw session identifiers.

Session identifiers are represented only by a short digest.

The first live invocation from a configured provider may add one bounded activation receipt (`decision=active`, `category=runtime`). That is a transport/readiness marker, **not** a risky-action finding and not a proof claim. Subsequent safe calls do not need to create repeated activation receipts.

Check aggregate state:

```bash
dw protect status
```

`dw status` and `dw doctor` also expose Protect health without treating `off` as a project error.

## Portal boundary

When Portal sync is configured, DiffWitness may send only an aggregate protection summary:

```text
mode
policy
health
receipt count
receipt-chain integrity
blocked count
observed count
confirmation-request count
```

Detailed categories, commands, source content and raw events do not cross that boundary.

Portal labels Protect as **OBSERVED** runtime metadata. It is deliberately stored and rendered separately from DiffWitness Proof assurance.

## Failure semantics

Protect is a runtime safety layer, so a failure in a configured pre-tool Protect hook fails closed for that action rather than manufacturing an allow decision.

Post-tool quality feedback is advisory. A post-tool helper failure does not create a false clean claim.

Proof remains independent: a Protect failure, disabled Protect mode or delegated external harness must never produce or suppress a DiffWitness proof certificate.

## Recommended alpha workflow

For a repository without another runtime harness:

```bash
dw doctor
dw protect detect
dw protect enable --policy standard
dw guard -- claude
```

For Codex builtin Protect, after enabling Protect complete Codex's provider-owned hook/trust flow before expecting runtime interception:

```bash
dw protect enable --policy standard
codex --enable hooks
# In Codex: accept the repository trust prompt, then review/approve DiffWitness in /hooks.
dw protect status
```

For a repository already using its own harness:

```bash
dw protect detect
dw protect use external
dw guard -- claude
```

For users who do not want live interception:

```bash
dw protect disable
dw guard -- claude
```

All three paths converge on the same post-change Proof and Debt semantics.
