TECHNICAL_HELP = """DiffWitness — understand, prove, control debt, and preserve continuity for AI-assisted code

Start here:
  dw setup                            Arm native Claude/Codex/Cursor integration for this Git project
  dw setup status                     Verify the installed DiffWitness integration
  dw status                           Show evidence readiness, current change, debt, and next actions
  dw explain                          Show the latest deterministic evidence-backed IdleProof explanation
  dw view guided                      Prefer simpler language over the same underlying truth
  dw doctor                           Preflight local evidence, debt, continuity, and advisory readiness

Core workflow:
After setup, use Claude Code, Codex, or Cursor normally. DiffWitness runs at the native task boundary:
  UNDERSTAND  explain what the agent is changing in this project
  PROVE       execute evidence against the exact Git change
  OWE         measure and persist software/debt obligations
  CONTINUITY  preserve bounded project memory for the next task/session/device

Optional presentation only (never changes evidence):
  dw explain --engine agent-session   Export bounded facts for the model already active in your coding session
  dw explain --engine local           Rephrase with your local Ollama/OpenAI-compatible model
  dw explain --engine openrouter      Rephrase with your own OpenRouter key/credits
  dw explain --engine custom          Rephrase with your own compatible endpoint

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

The saved view is a local presentation preference stored under `.git/diffwitness/`. Switching between
Guided and Technical changes presentation only: proof semantics, certificates, Debt Ledger state,
source code, repository HEAD, privacy boundaries, and machine-readable status contracts remain the same.
`dw status --view ...` can override the view for one invocation and `dw status --json` is view-invariant.

DiffWitness is local-first. Proof, Debt Ledger, deterministic IdleProof understanding, and Project
Continuity do not require a model API and do not upload source code. Optional presentation engines receive
only bounded evidence-derived facts and are explicitly user-owned unless a paid Portal plan enables
DiffWitness Managed AI. Portal sync, when configured, carries only the bounded product contract; raw
prompts, raw diffs, agent event streams, and source code stay out of Portal.

`dw status` is navigation over bounded evidence, Git metadata, and durable obligations; it is not a
correctness score. `dw guard` remains an explicit fallback for unsupported agents and automation.
Normal Claude/Codex/Cursor users should not need to wrap their agent after `dw setup`.

Use `dw <command> --help` for command-specific options.
"""

GUIDED_HELP = """DiffWitness · Guided view — understand what needs attention without hiding the evidence

Start here:
  dw setup                           Connect DiffWitness to Claude/Codex/Cursor for this Git project
  dw status                          Show what is known, what needs attention, and what to do next
  dw explain                         Explain the latest change from local evidence, with no AI required
  dw doctor                          Check whether the project is ready to produce executable evidence
  dw view technical                  Switch to exact engineering detail at any time

Useful follow-up actions:
  dw guard -- <agent>                Explicitly protect an unsupported agent/process when needed
  dw plan                            See which known technical obligations can be repaid next
  dw repay -- <agent>                Ask an agent to repay selected debt and verify the result

If you want smoother wording, `dw explain --help` shows optional local, current-agent, OpenRouter and
custom-provider presentation modes. They only rephrase the same evidence; the default remains local and
AI-free, and a Community user is never silently routed to DiffWitness-paid inference.

Guided view changes wording and disclosure only. It does not weaken verification, hide an UNKNOWN as
success, or change proof certificates, Debt Ledger state, project source, privacy boundaries, or the
machine-readable status contract. Source code and raw prompts/diffs stay local by default.

Need the complete engineering command surface now? Run `dw view technical`, then `dw --help` again.
You can switch back with `dw view guided` without reinstalling or changing the project.
"""

# Backward-compatible import for integrations/tests that expect the original constant.
PUBLIC_HELP = TECHNICAL_HELP


def help_for_view(view: str) -> str:
    return GUIDED_HELP if view == "guided" else TECHNICAL_HELP


__all__ = ["GUIDED_HELP", "PUBLIC_HELP", "TECHNICAL_HELP", "help_for_view"]
