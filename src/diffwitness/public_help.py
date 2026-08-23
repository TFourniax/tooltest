PUBLIC_HELP = """DiffWitness — evidence, software debt, and project continuity for AI-assisted code

Core workflow:
  dw guard [options] -- <agent>      Run Claude/Codex/another agent inside the proof + debt boundary
  dw gate [options]                  Validate an existing Git diff / pull request
  dw prove [options]                 Exhaustive hunk-level counterfactual evidence
  dw debt [options]                  Measure and record debt introduced by a change
  dw health [options]                Scan current project debt and reconcile the Debt Ledger
  dw plan [options]                  Build an automatically verifiable debt-repayment plan
  dw repay [options] -- <agent>      Run a constrained repayment mission and verify closure
  dw ledger <action> [options]       Inspect and govern durable DW-* obligations

Project continuity:
  dw context <task>                  Compile bounded task context from project memory + structure
  dw objective add <text>            Record a project objective
  dw decision record <text>          Record a decision and its rationale/relations
  dw invariant add <text>            Record a project invariant; --critical makes it always relevant
  dw failed-approach record <text>   Preserve an approach that should not be repeated
  dw state status                     Inspect the append-only journal and rebuildable Project State
  dw state graph [--entity ID]        Inspect typed project entities and relations
  dw state rebuild                    Rebuild state.db from ProjectEvents + Git

Evidence / interoperability:
  dw envelope [options]              Bind Proof + Debt + optional IdleProof to one exact dwchg_...
  dw verify <certificate> [options]  Verify certificate integrity and freshness
  dw note <certificate> [options]    Attach a verified proof reference using git notes
  dw core [options]                  Budgeted Adaptive Core / 1-minimal reduction search
  dw recheck <DW-...> [options]      Replay verification for historical debt lineages
  dw doctor [options]                Preflight evidence + advisory engine + continuity readiness

Start here:
  dw doctor
  dw guard --policy strict -- claude
  # or: dw guard --policy strict -- codex

With the Claude/Codex plugin installed, task-specific `dw context` is injected automatically at
UserPromptSubmit. Context is advisory; only executed DiffWitness evidence can establish VERIFIED
claims. Project memory is local-first and the continuity journal never stores raw prompts or raw diffs.

Use `dw <command> --help` for command-specific options.
"""

__all__ = ["PUBLIC_HELP"]
