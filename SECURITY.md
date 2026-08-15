# Security

DiffWitness executes the test command (and optional prepare command) supplied by the user. Those commands run with the **current user's operating-system permissions** inside disposable Git worktrees; a worktree is not an OS sandbox.

## Trust boundary

Treat these inputs as executable code:

- the repository being tested,
- `--test`,
- `--prepare`,
- package-manager lifecycle scripts invoked by either command.

Do not run untrusted repositories or commands merely because DiffWitness puts the checkout in a temporary worktree.

## What DiffWitness isolates

DiffWitness is designed to keep experimental code states away from the user's active checkout. It does not intentionally edit the active working-tree files, staging index, branch refs, or commits.

Git temporary objects and worktree metadata are created while analysis is running and cleaned/reclaimed through normal Git mechanisms.

## `--share` warning

`--share PATH` creates a symlink from the disposable worktree to the named path in the source repository. This improves performance for large dependency caches such as `node_modules`, but it deliberately weakens isolation: test code can mutate the shared target.

Prefer `--prepare` when strict separation is more important than speed.

## Secrets

Environment variables from the invoking process are inherited by test commands. DiffWitness does not redact them from child processes. Command output is captured and only its tail is placed in reports, but test output can still contain secrets.

Run sensitive projects with the same secret-minimization practices you would use for any local test runner.

## Reporting a vulnerability

Please open a GitHub security advisory for the repository rather than publishing exploit details in a normal issue when possible.
