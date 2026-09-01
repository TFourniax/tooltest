# IdleProof integration — pre-release before/after matrix

This is the release-gate record for the first human-test candidate. It compares the canonical product (`agent/ci-canonical-validation-20260828`) with the IdleProof/DiffWitness candidate and separates **automated pre-release readiness** from later **public-release packaging/branding work**.

Status legend:

- **PASS** — proved on the exact candidate by automated execution or exact Git comparison.
- **PASS / additive** — behavior intentionally added without replacing the previous authority/path.
- **HUMAN** — deliberately reserved for the owner's usability/readability walkthrough.
- **PUBLIC-ONLY** — does not block the private human-test pre-release, but must be resolved before a public community tag.

## Frozen proof set

- Core candidate: PR #6, branch `agent/idleproof-zero-cost-inference-v1-20260829`, based exactly on `agent/ci-canonical-validation-20260828` with `behind_by=0`.
- Portal candidate: PR #4, SHA `e141c65f9fbd5192045fc2e114e174df9bda000c`, based exactly on `agent/ci-canonical-validation-20260828` with `behind_by=0`.
- Private engine candidate: SHA `bfd3905dc096f26a6ed61fbd391f9e77d638c776`; candidate and canonical branches are **identical: 0 commits / 0 files**.
- Portal exact full preflight: GitHub Actions run `33398578700` — all Node 24, Node 22, Deno/Edge, DB replay/pgTAP and real-browser steps passed.
- Portal focused browser rehearsal: run `33398366187` — 2/2 Playwright scenarios passed, including auth, tenant isolation, scoped device ingest and deterministic explanation rendering.
- Core current head proof set: `test`, `ProofBench`, `ContinuityBench` and `integrated-product-smoke` all passed; installed-wheel commercial-alpha journeys passed on Linux, Windows and macOS.

| Surface | Canonical before | Candidate after | Risk checked | Evidence / gate | Status |
|---|---|---|---|---|---|
| Source of truth | Git + executed evidence + Proof/Debt | Identical authority; IdleProof only consumes bounded evidence | LLM becomes truth | architecture invariants + private exact compare | **PASS** |
| Private causal engine | Existing adaptive/causal engine | Bit-for-bit identical | AI contaminates proof | 0 commits / 0 files | **PASS** |
| Causal semantics | Contrast / necessity / sufficiency / interaction; unstable = inconclusive | Same | semantic regression | ProofBench + full core matrix | **PASS** |
| Gate | Existing proof policy | Same | explanation changes acceptance | installed-wheel Gate journeys | **PASS** |
| Guard | Proof + Debt + exact envelope | Same, then deterministic explanation artifact | presentation failure alters proof | Guard failure isolation + wheel journeys | **PASS / additive** |
| Debt Ledger | Hash-chained replayable obligations | Same | ledger corruption | ledger/integration journeys | **PASS** |
| Debt Sensors | Deterministic/advisory | Same, now explainable | heuristic becomes verified | confidence mapping tests | **PASS / additive** |
| Change envelope | Exact Proof/Debt/understanding correlation | Same envelope feeds explanation | parallel AI facts | Guard implementation + tests | **PASS / additive** |
| Continuity | Existing bounded context | Same plus bounded presentation policy | status upgrade/context drift | ContinuityBench | **PASS / additive** |
| Git worktree snapshot | Ignores narrow local runtime artifacts | Also ignores untracked `.idleproof` state and local IDE hooks at nested depths | setup changes proven tree | gitops implementation + matrix tests | **PASS** |
| Tracked project files | Always part of proof | Still always part of proof | over-broad exclusion | exclusion applies only to untracked local state | **PASS** |
| `SOUL.md` | N/A | Optional bounded style/vocabulary only | prompt overrides facts | context whitelist + tests | **PASS** |
| `dw explain` deterministic | N/A | No network/model; evidence-backed baseline | hidden inference call | exact installed-wheel release acceptance on 3 OS | **PASS** |
| Agent-session explanation | N/A | Reuses active user-paid coding session | invented evidence/cost shift | installed-wheel acceptance + non-canonical contract | **PASS** |
| Local model route | N/A | User hardware/OpenAI-compatible loopback | secret/network leak | transport tests + installed route contract | **PASS** |
| OpenRouter/BYOK | N/A | User key/user credits only | company pays or key persists | credential namespace/cache tests | **PASS** |
| Custom endpoint | N/A | Explicit user endpoint | plaintext key/redirect/query leak | redirect block, remote HTTP+key rejection, endpoint sanitization | **PASS** |
| OSS `managed` route | N/A | Deliberately unavailable; deterministic fallback | free user triggers company API | installed-wheel acceptance explicitly exercises rejection | **PASS** |
| LLM input context | N/A | Bounded whitelist of stored/evidence facts + style | raw source/prompt/diff exfiltration | validators + marker leakage tests | **PASS** |
| Provider output | N/A | Existing IDs only | model invents evidence units | invalid/duplicate ID rejection | **PASS** |
| Canonical wording | Deterministic | Deterministic `original` retained; AI text presentation-only | hallucination replaces truth | unit + installed acceptance | **PASS** |
| Output control chars | N/A | C0/C1/ESC stripped | terminal/control injection | provider-output tests | **PASS** |
| User-owned cache | N/A | Content-addressed under `.git/diffwitness`, bounded | key leak/source pollution | installed acceptance confirms cache hit and location | **PASS** |
| Community/free managed cost | No managed AI | 0 DiffWitness-paid calls | accidental variable cost | core policy + Portal DB gate | **PASS** |
| Builder quota | N/A | 500/month | runaway cost | policy + pgTAP | **PASS** |
| Pro quota | N/A | 1200/month | runaway cost | policy + pgTAP | **PASS** |
| Team quota | N/A | 1000/seat/month, finite | concurrent/unbounded pool | atomic DB reservation | **PASS** |
| Enterprise quota | N/A | 5000 default, contract cap 100000 | implicit unlimited | policy + pgTAP | **PASS** |
| Request bound | N/A | <=8k input, <=800 output, <=1 retry | cost explosion | policy/tests | **PASS** |
| Managed AI default | N/A | Disabled unless explicitly and completely configured | accidental provider call | server env fail-closed tests | **PASS** |
| Global spend breaker | N/A | Missing budget disables managed AI | company-wide runaway spend | fresh DB replay + pgTAP | **PASS** |
| First-request budget edge | N/A | Cannot create first reservation above budget | first insert bypass | explicit pre-check + pgTAP | **PASS** |
| Workspace concurrency | N/A | Atomic monthly reservation | race overshoot | SQL conflict guard + pgTAP | **PASS** |
| Provider credentials | N/A | Server-only, no URL credentials, HTTPS prod | browser/key disclosure | env tests + server boundary | **PASS** |
| Provider redirect | N/A | `redirect: error` | Authorization forwarding | unit test | **PASS** |
| Managed AI input authority | N/A | Client sends project/snapshot IDs only; server reloads RLS-protected receipt | forged facts | server implementation + tests | **PASS** |
| Managed AI output authority | N/A | `canonicalSource: deterministic`; rewrite presentation-only | evidence mutation | unit tests, no evidence write path | **PASS** |
| Portal snapshot privacy | Existing bounded receipt | Same | raw source/prompt/diff/secrets stored | Deno/Vitest + real ingest | **PASS** |
| Portal body boundary | Existing bounded ingest | Strict 64 KiB UTF-8/JSON | payload abuse | Edge validator tests | **PASS** |
| Portal RLS | Existing tenant isolation | Same plus private usage accounting | cross-tenant leak | DB replay/pgTAP + real two-user browser E2E | **PASS** |
| Cross-tenant project URL | Previously could surface generic failure in rehearsal | inaccessible project resolves as not-found before secondary RPCs | existence leak/500 | browser E2E proves denied project is not exposed | **PASS** |
| Portal UI authorities | UNDERSTAND / PROVE / OWE | Same plus deterministic explanation details | AI-first alternate workflow | production build + browser journey | **PASS / additive** |
| Proof language | Existing status | accepted/inconclusive/missing remain explicit | understanding mistaken for correctness | snapshot explanation tests + E2E inconclusive fixture | **PASS** |
| Technical view | Exact identifiers | Preserved | richer UX hides evidence | build/typecheck/browser | **PASS** |
| Portal durable Managed-AI cache | N/A | Not implemented or claimed | privacy/cache poisoning | explicitly out of scope | **PASS (not claimed)** |
| Portal Node 24 | Supported candidate build | clean install/build/typecheck/tests | runtime regression | exact preflight `33398578700` | **PASS** |
| Portal Node 22 | Supported candidate build | clean graph full app gate | compatibility regression | exact preflight `33398578700` | **PASS** |
| Portal unit/architecture gates | Existing | expanded inference/explanation suite | dependency regression | exact preflight | **PASS** |
| Portal migrations | Canonical schema | +2 managed-AI guardrail migrations | migration drift | rebuilt from zero | **PASS** |
| Portal pgTAP | Existing suite | expanded cost/RLS suite | SQL policy bug | all pgTAP passed from fresh DB | **PASS** |
| Portal signup confirmation | Existing | Same | auth regression | real Mailpit -> GoTrue -> callback -> dashboard | **PASS** |
| Portal logout/recovery/password | Existing | Same | auth/session regression | real browser first scenario | **PASS** |
| Portal tenant isolation | Existing | Same | data leakage | two independent browser contexts/projects | **PASS** |
| Device enrollment | Existing workflow | token shown once; setup command uses hidden/stdin token | token enters shell history | UI + browser assertions | **PASS** |
| Real device ingest | Existing workflow | canonical snapshot ID + scoped token | components work only in isolation | real Edge POST in browser rehearsal | **PASS** |
| Duplicate ingest | Existing idempotence | Same | replay duplicates records | same real snapshot returns duplicate | **PASS** |
| Wrong local project | Existing scope guard | Same | credential crosses project boundary | real Edge rejection | **PASS** |
| Ingest -> timeline -> explanation | Existing timeline | receipt renders deterministic What changed/Why/Check | disconnected subsystems | focused + full preflight browser runs | **PASS** |
| Inconclusive proof UI | Existing proof state | never upgraded to verified | overclaim | browser asserts `More evidence needed`, no `Causally verified` | **PASS** |
| Core Linux | Supported | Same | OS regression | Python 3.11–3.14 + wheel journey + binary | **PASS** |
| Core macOS | Supported | Same | OS regression | Python matrix + installed wheel + binary | **PASS** |
| Core Windows | Supported | Same | OS regression | Python matrix + installed wheel + binary | **PASS** |
| Release wheel | Existing | Includes deterministic explanation + bundled sidecar | source-only success masks packaging omission | clean wheel install + full release acceptance | **PASS** |
| Bundled `idleproof` executable | Previously external dependency assumption | Installed by same `diffwitness` wheel | fresh machine cannot run setup/portal | exact installed wheel checks executable/version | **PASS** |
| `dw setup` fresh install | Delegated to external sidecar | Same public command, sidecar bundled in wheel | hidden dependency | installed-wheel acceptance on Linux/Windows/macOS | **PASS** |
| `dw portal` fresh sync | Delegated to sidecar | Sidecar bundled; scoped token stored under `.git` | onboarding command fails | installed-wheel configure/sync/disconnect rehearsal | **PASS** |
| Wheel uninstall/reinstall | Basic install | Explicit clean uninstall and reinstall | stale executable masks package defect | release package preflight | **PASS** |
| Standalone `dw` binary | Existing | `dw explain --help` packaged | dynamic import omission | standalone smoke Linux/macOS/Windows | **PASS** |
| Composite GitHub Action | Existing | Same consumer boundary | Action regression | consumer-style E2E | **PASS** |
| ProofBench | Existing | Same | causal quality regression | current candidate workflow | **PASS** |
| ContinuityBench | Existing | Same | continuity regression | current candidate workflow | **PASS** |
| Integrated smoke | Existing | Same + additive explanation | cross-module regression | current candidate workflow | **PASS** |
| Native IDE assets | Existing | bounded explanation policy added | hooks/package break | plugin JSON + unit/install journeys | **PASS / additive** |
| Public repo identity | Temporary `TFourniax/tooltest` | Still temporary | community pins wrong identity | release naming decision | **PUBLIC-ONLY** |
| Public Action/version pin | Not final | must reference final public repo/tag | moving public semantics | release checklist | **PUBLIC-ONLY** |
| UX/readability judgment | N/A | richer explanation/onboarding/settings | correct but confusing | owner walkthrough | **HUMAN** |

## Pre-release interpretation

For the private first human test, all correctness, packaging, cross-platform, tenant-isolation, auth, DB, scoped-ingest, Proof/Debt and inference-cost gates above are automated **PASS**. The human walkthrough is intentionally the remaining gate because it evaluates comprehension and product feel rather than replacing machine-verifiable correctness.

The public repository name/action pin remain later public-release work and do **not** justify changing proof semantics or blocking the private RC.

Merge is still deferred until the human-test candidate has been frozen and the owner completes the walkthrough. A human-discovered defect returns the candidate to automated gates before any merge or public tag.
