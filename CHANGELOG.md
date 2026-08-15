# Changelog

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
