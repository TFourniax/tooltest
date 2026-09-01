# IdleProof inference policy

IdleProof is useful without a language model. The deterministic renderer is the product baseline; AI is an optional presentation layer.

## Non-negotiable cost invariant

A Community/free user must never create a paid inference charge for DiffWitness.

This is enforced by architecture, not by a billing convention:

- deterministic explanations require no model, network, account, or paid service;
- Community managed-inference allowance is `0`;
- unknown plans fail closed to Community semantics;
- a failed user-owned provider never falls back to a DiffWitness-paid provider;
- the safe fallback is always the deterministic explanation.

## Evidence-first explanation

After a guarded or IDE-integrated change, DiffWitness produces the same exact-bound Proof + Debt envelope used by the rest of the product. IdleProof then derives a local explanation artifact at:

```text
.git/diffwitness/idleproof-explanation.json
```

Run:

```bash
dw explain
```

or:

```bash
dw explain --json
```

The deterministic explanation is built from Git patch metadata, the accepted proof claim, and Debt Sensor output. It reports scope, why the change matters, findings, confidence, evidence locations, and suggested verification without asking a model to discover facts.

Heuristic findings remain advisory. DiffWitness never promotes them to VERIFIED.

## Available inference choices

All user-owned choices can coexist with the deterministic baseline:

1. **No AI** — deterministic local explanation.
2. **Current coding-agent session** — Claude Code, Codex, OpenCode, or another compatible agent can rephrase the evidence using the model the user is already running.
3. **Local model** — Ollama, LM Studio, vLLM, or another local OpenAI-compatible endpoint.
4. **OpenRouter / BYOK** — the user supplies their own provider account and credits.
5. **Custom endpoint** — private gateway, VPC endpoint, or another OpenAI-compatible service.
6. **DiffWitness Managed AI** — paid-plan convenience layer implemented by the Portal, with finite quotas and hard cost breakers.

The OSS core does not need a DiffWitness provider secret to work.

## Coding-agent sessions

The IDE harness injects an evidence-first presentation policy into compatible sessions. It does not create a second model request itself. The already-active session model may improve wording, but it may not invent behavior, risk, intent, causality, tests, evidence, or recommendations.

This means agent-session explanations consume the user's existing model/session rather than DiffWitness inference spend.

## `soul.md`

Optional presentation preferences can live in:

```text
.diffwitness/soul.md
.idleproof/soul.md
soul.md
```

The first available file is used. Local untracked IdleProof/DiffWitness soul files are excluded from the proof snapshot so changing tone does not change the candidate being proved. If a project deliberately tracks such a file, it remains normal repository content.

Soul instructions are bounded and are style-only. They can request language, tone, detail level, vocabulary, or teaching style. They cannot override evidence or make an advisory claim VERIFIED.

## Managed AI quotas

The commercial Portal owns managed-provider execution and billing policy. Current product limits are:

- Community/free: **0** DiffWitness-paid calls;
- Builder: **500** managed explanations/month;
- Pro: **1,200** managed explanations/month;
- Team: finite per-seat pool;
- Enterprise: finite contract/default pool, never implicitly unlimited.

When managed quota is exhausted, IdleProof keeps working. The user can continue with deterministic output, their agent session, local inference, OpenRouter/BYOK, or a custom endpoint.

## Request and spend boundaries

Managed inference must remain a presentation task over compact facts rather than repository-wide reasoning. The Portal therefore applies independent limits including:

- bounded evidence payload;
- bounded input/output tokens;
- at most one retry;
- per-workspace monthly quota reservation before provider contact;
- explicit global monthly spend budget before provider contact;
- provider-side hard credit/spend cap;
- deterministic fallback on provider failure or invalid output.

The global budget is deliberately opt-in. If operations has not provisioned a budget for the current month, managed inference stays disabled even for a paid workspace.

## LLM trust boundary

The managed model receives evidence-backed presentation units, not a whole repository. It may rewrite existing unit IDs but cannot add new units. Unknown IDs, malformed output, omissions, timeouts, or provider failures fall back to the deterministic original.

The intended hierarchy is:

```text
Proof + Debt evidence
        ↓
deterministic IdleProof explanation
        ↓
optional presentation model
        ↓
validated one-to-one rewrites
```

The model is never the source of truth.
