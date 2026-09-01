# Security

DiffWitness is a developer/CI analysis tool that **executes repository code**. Its security boundary should be understood before running it on untrusted changes.

## Trust model

`diffwitness prove --test "..."` and the `dw` proof workflows execute the supplied or auto-detected evidence command in detached Git worktrees representing base, candidate, and counterfactual variants. `--prepare` also executes a shell command.

This means a malicious base or candidate revision can execute arbitrary code with the permissions of the DiffWitness process whenever your selected command imports, builds, tests, or otherwise runs that revision.

Use the same isolation policy you would use for normal CI on untrusted pull requests: disposable runners/containers/VMs, least-privilege tokens, and no sensitive secrets.

## Protect runtime layer

`dw protect` is an optional local guard layer for supported agent hooks. It is **not** a sandbox and it is not the proof engine.

Modes:

- `builtin` — DiffWitness installs its own supported `PreToolUse` / `PostToolUse` hooks;
- `external` — live runtime safety is delegated to another harness;
- `off` — no DiffWitness Protect interception is installed.

Protect starts with a deliberately bounded high-confidence rule set. It cannot guarantee that every dangerous command, supply-chain action, secret, semantic bug or malicious tool invocation is detected.

A clean Protect result must never be interpreted as proof that the software is correct. Proof remains the independent post-change executable evidence boundary.

### Permission authority

Protect does not issue an allow decision for clean actions. It stays silent and leaves the coding agent's own permission system authoritative.

When builtin Protect is configured, failure of the pre-tool evaluation path fails closed for the affected action rather than manufacturing an allow decision. Post-tool checks are advisory and do not create a false clean claim if they fail.

### Hook coexistence

Builtin Protect modifies only the supported local hook configuration files and tracks the commands it manages. Disable/uninstall removes only DiffWitness-managed Protect hooks and preserves unrelated hooks.

High-confidence external-harness detection causes builtin activation to delegate by default unless `--force` is explicit. Existing foreign hooks without a high-confidence harness marker are treated as coexistence signals and are not deleted.

### Protect receipts

Bounded local runtime receipts live under:

```text
.git/diffwitness/protection.jsonl
```

They form a SHA-256 hash-linked chain for local integrity checks. They intentionally do not store raw commands, source-file contents, raw prompts, raw agent-event streams or raw session identifiers. Session identity is represented by a short digest.

The local receipt chain is an integrity mechanism, not an external signature. A repository owner with filesystem access can replace local metadata.

When Portal sync is configured, only aggregate Protect metadata may cross the boundary: mode, policy, health, receipt count/integrity and aggregate blocked/observed/confirmation counts. Detailed runtime categories, commands and raw events remain local.

## GitHub Actions

For pull requests from untrusted contributors:

- prefer `pull_request`, not `pull_request_target`, for workflows that execute candidate code;
- grant only the permissions required by the workflow (`contents: read` is enough for the provided PR action example);
- do not expose write-capable repository tokens or deployment secrets to the evidence command;
- use ephemeral hosted runners or equivalent isolation;
- do not publish Debt Ledger checkpoints from a workflow that executes untrusted candidate code.

The provided composite Action may **read** the portable Debt Ledger baseline to enforce cumulative budgets. It deliberately does not push the shared ledger ref from a PR run. Publish checkpoints only from a trusted post-merge/default-branch workflow or an explicit maintainer operation with narrowly scoped write credentials.

DiffWitness annotations and step summaries do not require a write-capable GitHub API token.

## Debt Ledger integrity

The default local ledger is stored at:

```text
.git/diffwitness/debt-ledger.jsonl
```

Local writes use a process lock and atomic file replacement. Ledger events form a SHA-256 hash chain and imported histories are also checked for valid state transitions.

These mechanisms protect against accidental corruption, stale concurrent writers and unnoticed history divergence. They are **not a digital signature** and do not prove that a repository owner with filesystem/Git-object access could not deliberately rewrite a complete history.

Portable checkpoints use the dedicated ref:

```text
refs/diffwitness/debt-ledger
```

`dw ledger push` uses a normal non-force Git push. A concurrent remote update therefore fails instead of being overwritten. `dw ledger pull` refuses divergent event histories rather than inventing an automatic merge.

Authentication/network failures during ledger synchronization fail closed. Only a genuinely absent remote checkpoint may be treated as first use; pass `dw ledger pull --required` when even first-use fallback is not acceptable.

A future external-attestation/signature layer would be required for stronger cross-party authenticity.

## `--share`

`--share PATH` creates a symlink from each sandbox to a path in the source checkout. It is intended for expensive dependency/cache directories such as `node_modules`.

Tests and build scripts in any analyzed revision can mutate that shared target. Never share credentials, source-of-truth data, or state that must remain isolated between counterfactual runs.

## Worktree snapshots

`WORKTREE` uses an alternate Git index to snapshot staged, unstaged and non-ignored untracked content into an unreachable commit. It does not intentionally modify the user's real index/staging area.

Project health analysis also snapshots the current worktree before scanning it, then scans an immutable detached worktree of that snapshot. This prevents a dirty checkout from being analyzed while the report incorrectly claims to represent `HEAD`.

Unreachable snapshot commits may eventually be garbage-collected by Git. Reports include the tree identity needed to bind the analyzed content even when the ephemeral commit is later pruned.

## Reports and provenance

Evidence certificates and debt reports can include command strings, repository paths, output tails, environment metadata, Git SHAs, rule evidence and agent/executable provenance. Review artifacts before publishing if those fields could reveal sensitive information.

Agent prompts and full command arguments are intentionally not persisted in Debt Ledger provenance by default because they can contain secrets or private data.

Protect receipts use a stricter bounded runtime schema and intentionally exclude raw commands/content as described above.

## Reporting vulnerabilities

Please report security-sensitive issues privately to the repository owner rather than opening a public issue with exploit details.
