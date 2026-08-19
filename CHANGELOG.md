# Changelog

## 0.4.0a1 — Proof + Debt Control Alpha

DiffWitness extends the proof layer into a replayable software-debt control loop for agent-generated changes.

### Added

- Event-sourced Debt Ledger with stable `DW-...` lineages, explicit provenance, acceptance, resolution, reopening, history, and budget accounting.
- `dw debt`, `dw health`, `dw plan`, `dw repay`, `dw recheck`, and public `dw ledger` lifecycle commands.
- Causal, deterministic, historical, and explicitly bounded heuristic debt measurements.
- Replay adapters for mutation necessity, historical test discrimination, and project-level rules.
- Debt budgets for total debt, per-change debt, and category-specific ceilings.
- Portable Debt Ledger checkpoints on `refs/diffwitness/debt-ledger` with safe pull/push semantics for ephemeral clones and CI.
- GitHub Action debt outputs plus automatic read-only restoration of the cumulative ledger baseline.
- Immutable worktree snapshots for project-health provenance.

### Hardened

- Local ledger writes are atomic, fsynced where supported, and protected by a dependency-free inter-process lock.
- State decisions and event appends are transactional, preventing two agents from double-introducing a lineage or acting on stale debt state.
- Hash-valid but semantically impossible ledger histories fail closed.
- Remote checkpoint updates are fast-forward only; concurrent writers cannot force-overwrite another ledger history.
- Failed Git transport cannot masquerade as a missing/empty cumulative ledger.
- Proof certificates must pass integrity and candidate-content binding before debt accounting trusts their provenance.
- Merely supplying a certificate file no longer suppresses `unverified_change`; only accepted behavioral evidence can do so.
- Mutation rechecks reset test side effects before executing the counterfactual variant.
- Health scans bind findings to the exact immutable tree that was actually inspected, including dirty-worktree content.

### Alpha boundary

- The 0.4 line is intentionally marked alpha while the public repository/distribution path and real-world adopter feedback are exercised.
- Debt points are accounting weights over inspectable obligations, not bug probabilities, engineering-time estimates, or a universal maintainability score.
- Hash chains are integrity mechanisms, not external signatures against a malicious repository owner.

## 0.3.0 — Proof Layer

DiffWitness moves from a hunk-evidence CLI toward an agent-independent proof layer for code changes.

### Added

- `dw` low-friction frontend.
- `dw guard -- <agent>` before/after proof boundary for Claude Code, Codex, humans/scripts launched as subprocesses, and other coding agents.
- `dw gate` unified PR/CI proof gate.
- Automatic strategy selection: exhaustive real-hunk proof for small patches, budgeted Adaptive Core for large patches.
- Adaptive Core delta-debugging search over real production mutations with explicit budget and 1-minimality semantics.
- `observe`, `balanced`, and `strict` downstream proof policies.
- Zero-config evidence discovery for common Python, JavaScript/TypeScript, Rust, Go, JVM, PHP, and Ruby project signals.
- Formal `proof-not-required` certificates for documentation/test-only changes rather than manufacturing unrelated test evidence.
- Narrow documentation classifier while keeping build/configuration/migration files in the causal surface.
- `dw verify` certificate integrity and Git-tree freshness checks.
- `dw note` verified proof attachment through `refs/notes/diffwitness` without rewriting commit SHAs.
- Artifact-safe worktree verification for untracked generated evidence files.
- Claude Code plugin manifest, marketplace manifest, lifecycle hooks, and DiffWitness skill.
- Codex plugin manifest, lifecycle hook surface, and shared skill.
- Shared plugin hook bridge with `PLUGIN_ROOT` / `CLAUDE_PLUGIN_ROOT` support.
- GitHub Action now routes through the same automatic Gate and preserves evidence artifacts.
- Proof protocol, Guard, Gate, and attestation documentation.

### Hardened

- Candidate and base variants are classified for stability before causal labels are assigned.
- Adaptive Core refuses causal minimization without stable base-fail -> candidate-pass contrast.
- Combinatorial searches stream under explicit budgets instead of materializing unbounded combination sets.
- Public Guard delegates proof decisions to Gate so local and CI policy semantics do not drift.
- Windows Unicode console handling.
- Runtime/package version consistency is enforced by CI.
- Plugin JSON, package compilation, CLI entrypoints, wheel build, and six-platform Python/OS matrix are exercised in CI.

### Evidence boundary

DiffWitness still does not claim mathematical program correctness. All conclusions remain relative to executable evidence, environment, search completeness, and stability. Unknown evidence remains explicit rather than becoming a confidence score.

## 0.2.0 — Causal Evidence Engine

- Repeated-run stability classification.
- Candidate-test overlay onto base.
- Real-hunk necessity map.
- Minimal sufficient subset search.
- Hidden mutual-backup interaction search.
- Evidence certificates and GitHub annotations.
- Greedy patch minimization.

## 0.1.0 — DiffWitness Prototype

- Reverse-ablate each real production Git hunk.
- Classify changes as witnessed, unwitnessed, or inconclusive under a selected test command.
