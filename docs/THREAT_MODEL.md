# DiffWitness threat model

DiffWitness is a **proof orchestration layer**, not an operating-system security sandbox.

It intentionally executes the repository's evidence command against multiple code variants. A malicious test command or malicious candidate repository code therefore has the same ability to execute as any other test step run by that user/CI runner.

## Trust boundaries

DiffWitness isolates **repository state** with disposable Git worktrees. That protects the active checkout from the normal mechanics of patch ablation and counterfactual replay.

It does **not** provide process, network, filesystem, kernel, container, or secret isolation.

### Protected by DiffWitness

- the active checkout is not repeatedly rewritten for counterfactual experiments;
- WORKTREE capture uses an alternate Git index, not the user's staging index;
- generated verification exclusions operate on an ephemeral index;
- proof certificates bind to exact Git content trees;
- stale/tampered certificates can be rejected;
- unstable evidence is not converted into a causal label.

### Not protected by DiffWitness

The evidence command can still:

- access files its operating-system user can access;
- use network access available to the runner;
- read environment variables and secrets available to the process;
- start child processes;
- mutate explicitly shared cache/dependency paths;
- exploit vulnerabilities in dependencies, language runtimes, or the host.

Use containers/VMs/ephemeral hosted runners when hostile code requires security isolation.

## Public pull requests

Prefer the ordinary GitHub `pull_request` event with minimum permissions:

```yaml
on:
  pull_request:

permissions:
  contents: read
```

Do **not** combine execution of untrusted candidate code with privileged `pull_request_target` workflows. `pull_request_target` runs in the base-repository security context and can expose permissions/secrets that should not be given to fork code.

The DiffWitness example Action intentionally needs no write permission to analyze a PR.

## Secrets

Do not inject production secrets into a job that executes untrusted candidate tests merely because the job also runs DiffWitness.

DiffWitness does not require model API keys. Keep the proof job independent from deployment credentials where possible.

## Self-hosted runners

A self-hosted runner is part of your trust boundary. Repository tests can affect it outside the temporary Git worktrees if the operating-system account permits that.

For untrusted public contributions, prefer ephemeral/disposable runners or an isolation layer designed for hostile workloads.

## `--share`

`--share PATH` symlinks a repository-relative source path into proof worktrees to reduce setup cost (for example a dependency cache).

This is a performance feature, **not isolation**. Evidence can mutate the shared target. Do not share sensitive or integrity-critical host directories.

## Agent Guard

`dw guard -- <agent>` runs the selected agent as a normal subprocess in the repository. DiffWitness captures before/after Git state; it does not sandbox the agent itself.

Use the agent vendor's own permission/sandbox controls in addition to DiffWitness. DiffWitness's job is to independently interrogate the resulting patch, not to replace execution permissions.

## Certificate security

A content-addressed certificate proves integrity only relative to its hash construction. `dw verify` additionally checks that its candidate tree still matches the requested repository state.

A valid certificate does not authenticate the human/machine identity that generated it. Git notes similarly associate a proof reference with a commit but are not a digital signature.

Future signing integrations may authenticate provenance; they must remain separate from the causal evidence claim itself.

## Reporting security issues

Do not publish exploit details for an unpatched DiffWitness vulnerability in a public issue. Follow the repository's `SECURITY.md` reporting guidance.
