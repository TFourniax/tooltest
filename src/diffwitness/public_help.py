from .language import tr
from .public_help_fr import GUIDED_HELP_FR, TECHNICAL_HELP_FR

TECHNICAL_HELP = """DiffWitness — protect agent actions, understand, prove, control debt, and preserve continuity for AI-assisted code

Start here:
  dw setup                            Arm native Claude/Codex/Cursor integration for this Git project
  dw setup status                     Verify the installed DiffWitness integration
  dw status                           Show Protect, evidence readiness, current change, debt, and next actions
  dw protect detect                   Detect external harness / hook activity and recommend a runtime mode
  dw protect enable                   Enable optional builtin runtime guards for supported agents
  dw explain                          Show the latest deterministic evidence-backed IdleProof explanation
  dw view guided                      Prefer simpler language over the same underlying truth
  dw doctor                           Preflight runtime protection, evidence, debt, continuity, and readiness

Core workflow:
After setup, use Claude Code, Codex, or Cursor normally. DiffWitness keeps distinct boundaries:
  PROTECT     optional runtime safety: builtin / external / off; observations are not proof
  UNDERSTAND  explain what the agent is changing in this project
  PROVE       execute evidence against the exact Git change
  OWE         measure and persist software/debt obligations
  CONTINUITY  preserve bounded project memory for the next task/session/device

Protect (optional live runtime layer):
  dw protect detect                   Inspect harness/hook signals without changing configuration
  dw protect enable [--policy ...]    Install builtin Claude/Codex PreTool/PostTool guards
  dw protect use external             Delegate live safety to another harness; keep Proof/Debt active
  dw protect disable                  Remove DiffWitness Protect hooks; keep Proof/Debt active
  dw protect status [--json]          Inspect mode, health and aggregate bounded receipts
  dw protect log [--json]             Inspect local bounded runtime receipts

Protect policy is independent from Guard proof policy. Clean actions are never force-allowed by
DiffWitness; provider-native permissions remain authoritative. `off` installs no Protect interception.
Current Codex hooks are provider-feature/trust gated: DiffWitness installs configuration but never writes
Codex project/hook trust. Complete Codex's own trust flow (including `/hooks`) and use `dw protect status`
to confirm that a live hook has actually reached Protect.

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
  dw ide-hook <event>                  Native IDE protocol (normally installed by `dw setup` / Protect)

The saved view is a local presentation preference stored under per-worktree Git metadata. Switching between
Guided and Technical changes presentation only: Protect mode, proof semantics, certificates, Debt Ledger
state, source code, repository HEAD, privacy boundaries, and machine-readable status contracts remain the
same. `dw status --view ...` can override the view for one invocation and `dw status --json` is view-invariant.

DiffWitness is local-first. Protect, Proof, Debt Ledger, deterministic IdleProof understanding, and Project
Continuity do not require a model API and do not upload source code. Optional presentation engines receive
only bounded evidence-derived facts and are explicitly user-owned unless a paid Portal plan enables
DiffWitness Managed AI. Portal sync, when configured, carries only the bounded product contract; raw
prompts, raw diffs, raw commands, agent event streams, and source code stay out of Portal.

`dw status` is navigation over bounded runtime observations, evidence, Git metadata, and durable obligations;
it is not a correctness score. Native setup is the primary Claude/Codex workflow. `dw guard` remains the
stable explicit fallback for any agent/process when a deliberate process boundary is needed. Builtin Protect
currently targets supported Claude/Codex live hook surfaces.

Use `dw <command> --help` for command-specific options.
"""

GUIDED_HELP = """DiffWitness · Guided view — understand what changed, what is verified, and what needs attention

Start here:
  dw setup                           Connect DiffWitness to Claude/Codex/Cursor for this Git project
  dw status                          See what is known, unknown, and what to do next
After setup, use your coding agent normally; run `dw status` after a change.

Useful when needed:
  dw explain                         Explain the latest change from local evidence, with no AI required
  dw protect detect                  Check optional live protection without changing configuration
  dw view technical                  Open the complete engineering command surface

A blocked or observed runtime action is not proof that the final software works.
DiffWitness verifies the resulting Git change independently. Source code and raw prompts/diffs stay local by default.

For every command and advanced workflow: `dw view technical`, then `dw --help`.
"""

# Backward-compatible import for integrations/tests that expect the original constant.
PUBLIC_HELP = TECHNICAL_HELP


def help_for_view(view: str) -> str:
    body = tr(GUIDED_HELP, GUIDED_HELP_FR) if view == "guided" else tr(TECHNICAL_HELP, TECHNICAL_HELP_FR)
    return body + tr("\nLanguage: English by default. Save with `dw language en|fr`; override once with `dw --language en|fr <command>`. OS locale never selects product language.\n", "\nLangue : anglais par défaut. Enregistrer avec `dw language en|fr` ; une invocation avec `dw --language en|fr <commande>`. La locale ne choisit jamais la langue produit.\n")


__all__ = ["GUIDED_HELP", "PUBLIC_HELP", "TECHNICAL_HELP", "help_for_view"]
