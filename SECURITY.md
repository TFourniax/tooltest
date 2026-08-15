# Security

DiffWitness is a developer/CI analysis tool that **executes repository code**. Its security boundary should be understood before running it on untrusted changes.

## Trust model

`diffwitness prove --test "..."` executes the supplied shell command in detached Git worktrees representing base, candidate, and counterfactual variants. `--prepare` also executes a shell command.

This means a malicious base or candidate revision can execute arbitrary code with the permissions of the DiffWitness process whenever your selected command imports, builds, tests, or otherwise runs that revision.

Use the same isolation policy you would use for normal CI on untrusted pull requests: disposable runners/containers/VMs, least-privilege tokens, and no sensitive secrets.

## GitHub Actions

For pull requests from untrusted contributors:

- prefer `pull_request`, not `pull_request_target`, for workflows that execute candidate code;
- grant only the permissions required by the workflow (`contents: read` is enough for the provided action example);
- do not expose write-capable repository tokens or deployment secrets to the evidence command;
- use ephemeral hosted runners or equivalent isolation.

DiffWitness annotations and step summaries do not require a write-capable GitHub API token.

## `--share`

`--share PATH` creates a symlink from each sandbox to a path in the source checkout. It is intended for expensive dependency/cache directories such as `node_modules`.

Tests and build scripts in any analyzed revision can mutate that shared target. Never share credentials, source-of-truth data, or state that must remain isolated between counterfactual runs.

## Worktree snapshot

`WORKTREE` uses an alternate Git index to snapshot staged, unstaged and non-ignored untracked content into an unreachable commit. It does not intentionally modify the user's real index/staging area.

## Reports

Evidence certificates include command strings, repository paths, output tails, environment metadata, and Git SHAs. Review them before publishing if those fields could reveal sensitive information.

## Reporting vulnerabilities

Please report security-sensitive issues privately to the repository owner rather than opening a public issue with exploit details.
