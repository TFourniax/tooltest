PUBLIC_HELP = """DiffWitness — understand, prove, control debt, and preserve continuity for AI-assisted code

Start here:
  dw setup                            Arm native Claude/Codex/Cursor integration for this Git project
  dw setup status                     Verify the installed DiffWitness integration
  dw doctor                           Preflight local evidence, debt, and continuity readiness

After setup, use Claude Code, Codex, or Cursor normally. DiffWitness runs at the native task boundary:
  UNDERSTAND  explain what the agent is changing in this project
  PROVE       execute evidence against the exact Git change
  OWE         measure and persist software/debt obligations
  CONTINUITY  preserve bounded project memory for the next task/session/device

Portal (optional cloud history):
  dw portal identity [--json]         Show the local project/device enrollment identity
  dw portal configure ...             Configure the scoped ingest endpoint without exposing tokens in argv
  dw portal status [--json]           Inspect local delivery/queue state
  dw portal sync [--json]             Flush the bounded privacy-safe snapshot queue
  dw portal disconnect                Remove the local Portal credential configuration

Explicit/manual workflows:
  dw guard [options] -- <agent>        Run any agent/process inside an explicit proof + debt boundary
  dw gate [options]                    Validate an existing Git diff / pull request
  dw prove [options]                   Exhaustive hunk-level counterfactual evidence
  dw debt [options]                    Measure and record debt introduced by a change
  dw health [options]                  Scan current project debt and reconcile the Debt Ledger
  dw plan [options]                    Build an automatically verifiable debt-repayment plan
  dw repay [options] -- <agent>        Run a constrained repayment mission and verify closure
  dw ledger <action> [options]         Inspect and govern durable DW-* obligations

Project continuity:
  dw context <task>                    Compile bounded task context from project memory + structure
  dw objective add <text>              Record a project objective
  dw decision record <text>            Record a decision and its rationale/relations
  dw invariant add <text>              Record a project invariant; --critical makes it always relevant
  dw failed-approach record <text>     Preserve an approach that should not be repeated
  dw relation add A <type> B           Add a typed human-declared relation between existing facts
  dw state status                      Inspect the append-only journal and rebuildable Project State
  dw state graph [--entity ID]         Inspect typed project entities and relations
  dw state rebuild                     Rebuild state.db from ProjectEvents + Git
  dw state checkpoint                  Checkpoint ProjectEvents on refs/diffwitness/project-events
  dw state push                        Push that ref without force; concurrent writers cannot be lost
  dw state pull                        Fast-forward project memory on a fresh clone/machine

Evidence / interoperability:
  dw envelope [options]                Bind Proof + Debt + optional understanding to one exact dwchg_...
  dw verify <certificate> [options]    Verify certificate integrity and freshness
  dw note <certificate> [options]      Attach a verified proof reference using git notes
  dw core [options]                    Budgeted Adaptive Core / 1-minimal reduction search
  dw recheck <DW-...> [options]        Replay verification for historical debt lineages
  dw ide-hook <event>                  Native IDE protocol (normally installed by `dw setup`)

DiffWitness is local-first. Proof, Debt Ledger, understanding, and Project Continuity do not require a
model API and do not upload source code. Portal sync, when configured, carries only the bounded product
contract; raw prompts, raw diffs, agent event streams, and source code stay out of Portal.

`dw guard` remains available as an explicit fallback for unsupported agents and automation. Normal
Claude/Codex/Cursor users should not need to wrap their agent after `dw setup`.

Use `dw <command> --help` for command-specific options.
"""

__all__ = ["PUBLIC_HELP"]
