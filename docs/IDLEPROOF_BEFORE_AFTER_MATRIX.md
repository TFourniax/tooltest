# IdleProof integration — exhaustive before/after release matrix

This document compares the canonical pre-inference product (`agent/ci-canonical-validation-20260828`) with the IdleProof inference candidate. It is a regression/release checklist, not marketing copy.

Status legend:

- **PASS** — exercised by an automated gate on the exact candidate or established by an exact Git comparison.
- **PASS / additive** — behavior changed intentionally without replacing the previous authority/path.
- **PENDING** — implemented or statically reviewed but the exact release rehearsal has not yet completed.
- **BLOCKER** — a real user-facing release dependency is missing or not reproducibly distributed.
- **HUMAN** — intentionally left for the final personal usability pass; not a substitute for automated correctness/security gates.

| Surface | Canonical before | Candidate after | Changed? | Main risk | Evidence / gate | Status |
|---|---|---|---|---|---|---|
| Source of truth | Git + executed evidence + Proof/Debt | Identical authority; IdleProof consumes the bounded result | Additive | LLM becomes truth | Private engine exact compare + architecture invariant tests | **PASS** |
| Private causal engine | Existing private adaptive/causal engine | Bit-for-bit identical branch | No | AI contaminates proof | `diffwitness-private` canonical vs candidate: 0 commits / 0 files | **PASS** |
| DiffWitness causal semantics | Contrast/necessity/sufficiency/interaction, unstable = inconclusive | Same | No intended semantic change | Proof overstatement/regression | ProofBench + full core test matrix | **PASS** |
| Gate | Existing proof policy | Same public Gate | No | New explanation changes acceptance | Core CI + architecture import boundary | **PASS** |
| Guard | Proof + optional Debt + exact envelope | Same, then deterministic explanation artifact from same frozen base/candidate | Additive | Presentation failure changes accepted proof | Guard catches explanation failure and preserves Proof/Debt; installed-wheel journeys | **PASS / additive** |
| Debt Ledger | Hash-chained durable obligations | Same | No | Rewrite/corrupt ledger | Existing ledger integrity + wheel journeys | **PASS** |
| Debt Sensors | Deterministic/advisory sensors | Same; findings can be rendered by IdleProof | Additive presentation | Heuristic promoted to verified | `measurement -> confidence` tests; heuristics remain advisory | **PASS** |
| Change envelope | Exact-bound Proof/Debt/understanding correlation | Same envelope is upstream of explanation | Additive consumer | Parallel/independent AI context | Guard implementation + tests | **PASS** |
| Project Continuity | Existing local bounded context | Same; agent-session explanation policy appended | Additive | Context status upgrade | ContinuityBench + epistemic policy | **PASS** |
| Git snapshot | Tool-local untracked artifacts excluded | Adds local soul exclusion as tool state | Small | Soul/cache changes candidate tree | soul snapshot + nested plumbing tests | **PASS** |
| `SOUL.md` | Not part of IdleProof inference | Optional style/vocabulary only, bounded | New | Prompt changes facts | context whitelist + style note tests | **PASS** |
| Default `dw explain` | Not available | Deterministic, local, no network/model | New | Hidden paid call | installed/unit tests + provenance flags | **PENDING exact installed rehearsal** |
| Agent-session explanation | No explicit bounded presentation contract | Active coding-session model may rephrase bounded facts | New | Session model invents evidence | output policy + bounded context + non-canonical presentation | **PENDING exact installed rehearsal** |
| Local model route | No explicit route | Ollama/LM Studio/OpenAI-compatible loopback, user hardware | New | Secret/network leak | transport tests + no managed creds | **PENDING exact installed rehearsal** |
| OpenRouter route | No explicit route | User's `OPENROUTER_API_KEY` only | New | DiffWitness pays / key persisted | API-key namespace + cache tests | **PENDING exact installed rehearsal** |
| Custom provider route | No explicit route | Explicit OpenAI-compatible URL | New | plaintext key, redirect leak, URL-secret leak | no redirects; remote HTTP+key rejected; query hidden | **PENDING exact installed rehearsal** |
| OSS `managed` route | N/A | Deliberately unavailable; deterministic fallback | New | Free user triggers company bill | CLI code/tests; installed rehearsal added | **PENDING exact installed rehearsal** |
| LLM context | N/A | Whitelist of bounded facts + style only | New | raw source/prompt leaves machine | unit tests exclude raw code/prompt; Portal strict validator | **PASS** |
| Provider output | N/A | Rewrite only existing unit IDs | New | invented evidence | unknown IDs/duplicates rejected | **PASS** |
| Canonical wording | Deterministic product wording | Deterministic `original` always retained; AI text is presentation-only | New | hallucination replaces truth | unit tests + output structure | **PASS** |
| Terminal safety | N/A | C0/C1/ESC stripped from provider output | New | terminal escape injection | provider-output tests | **PASS** |
| User-owned cache | N/A | Content-addressed cache under `.git/diffwitness`, 16 entries / 1 MB | New | credential/cache leakage; source pollution | cache tests; no API key stored | **PENDING exact installed rehearsal** |
| Free plan inference cost | No managed AI | 0 company-paid calls, deterministic/user-owned routes only | Policy added | accidental variable cost | shared policy + Portal pgTAP | **PASS** |
| Builder managed quota | N/A | 500/month | New | cost runaway | core policy + DB pgTAP | **PASS** |
| Pro managed quota | N/A | 1200/month | New | cost runaway | core policy + DB pgTAP | **PASS** |
| Team managed quota | N/A | 1000/active seat/month | New | unbounded seat pool/request race | finite policy + atomic DB reservation | **PASS** |
| Enterprise managed quota | N/A | 5000 default; contract override capped 100000 | New | `unlimited` semantics | finite core/Portal policy + pgTAP | **PASS** |
| Managed request bounds | N/A | <=8k input, <=800 output, <=1 retry | New | provider cost explosion | Portal policy/tests | **PASS** |
| Global spend breaker | N/A | explicit budget; absent budget disables Managed AI | New | company-wide runaway spend | zero-db replay + `021_managed_ai_cost_boundary.sql` | **PASS** |
| First-request spend edge | N/A | reservation rejected if budget < conservative request reservation | New | first insert overshoots budget | regression fixed and pgTAP passes | **PASS** |
| Workspace quota concurrency | N/A | atomic reservation | New | concurrent overshoot | DB implementation + pgTAP | **PASS** |
| Managed provider credentials | N/A | server-only | New | browser/key disclosure | server env boundary; URL validation | **PASS** |
| Managed AI input authority | N/A | Browser sends only projectId/snapshotId; server reloads stored receipt/assurance | New | browser forges facts | server-side context builder + tests | **PASS** |
| Managed AI output authority | N/A | `canonicalSource: deterministic`; rewrite presentation-only | New | model changes persisted evidence | unit tests; no evidence mutation path | **PASS** |
| Portal snapshot privacy | Existing strict bounded snapshot | Same, including new assurance consumption | No weakening | raw code/prompt/diff/secrets stored | strict recursive validator + Deno/Vitest | **PASS** |
| Portal body boundary | Existing bounded ingest | 64 KiB strict UTF-8/JSON | No weakening | payload abuse | validator/Edge tests | **PASS** |
| Portal RLS / tenant isolation | Existing multi-tenant RLS | Same plus private managed-AI accounting | Additive | cross-tenant leakage | fresh DB replay + real browser two-tenant E2E | **PASS** |
| Portal project UI | UNDERSTAND / PROVE / OWE | Same three authorities + deterministic explanation details | Additive | AI-first alternate workflow | production build + route tests + browser base journey | **PASS / additive** |
| Guided proof language | Existing status | Explicit accepted/inconclusive/missing distinctions | Improved | “understood” mistaken for “correct” | shared snapshot explanation tests | **PASS** |
| Technical view | Existing exact identifiers | Preserved | No removal | guided UX hides evidence | production build/typecheck | **PASS** |
| Portal Managed AI durable cache | N/A | Not implemented | No claim | false claim / privacy complexity | explicitly out of scope | **PASS (not claimed)** |
| Portal app Node 24 | Canonical build | Candidate build | Regression gate | build/runtime break | exact self-hosted preflight | **PASS** |
| Portal app Node 22 | Canonical build | Candidate clean graph/build/tests | Regression gate | compatibility break | exact self-hosted preflight | **PASS** |
| Portal unit tests | Existing | 59 tests including new inference/explanation policy | Expanded | integration regressions | exact self-hosted preflight | **PASS** |
| Portal architecture gate | Existing | 70 source files scanned | Expanded source | forbidden dependency direction | exact self-hosted preflight | **PASS** |
| Portal migrations | 34 canonical migrations before feature | 36 canonical migrations | +2 | migration drift/replay failure | database rebuilt from zero | **PASS** |
| Portal pgTAP | Existing DB suite | 66 tests / 5 files | Expanded | RLS/quota/DB policy bug | exact self-hosted preflight | **PASS** |
| Portal browser auth | Existing | Real signup/confirmation/logout/recovery | No intended change | auth regression | Playwright 1.62.1 production build | **PASS** |
| Portal browser tenant isolation | Existing | Two independent users/projects, cross-tenant denial | No intended change | data leak | Playwright real browser E2E | **PASS** |
| Portal device enrollment -> actual snapshot -> explanation UI | Product workflow exists | Same workflow should expose new explanation | Intended integration | parts work independently but not together | needs one full browser/Edge ingest rehearsal | **PENDING** |
| Core Linux | Supported | Same | No | OS regression | Python 3.11–3.14 + wheel journey | **PASS** |
| Core macOS | Supported | Same | No | OS regression | Python matrix + wheel + binary | **PASS** |
| Core Windows | Supported | Same | No | OS regression | Python matrix + wheel + binary | **PASS** |
| Python release wheel | Supported | Includes IdleProof modules | Expanded | source tests pass but wheel omits files | wheel build/install smoke; enhanced inference rehearsal pending | **PENDING exact installed rehearsal** |
| Uninstall/reinstall | Basic package install | Explicit reinstall rehearsal added | Expanded | stale editable/source state masks packaging issue | release-package CI pending | **PENDING** |
| Standalone binary | Existing `dw` binary | `dw explain` included | Expanded | dynamic import omitted by PyInstaller | binary smoke now includes `dw explain --help` | **PENDING latest CI** |
| Composite GitHub Action | Existing | Same | No | feature changes Action consumer behavior | consumer-style Action E2E | **PASS** |
| ProofBench | Existing | Same | No | causal-quality regression | workflow success on candidate | **PASS** |
| ContinuityBench | Existing | Same | No | memory/context regression | workflow success on candidate | **PASS** |
| Integrated product smoke | Existing | Same + additive explanation | Additive | cross-module regression | workflow success on candidate | **PASS** |
| Native Claude/Codex plugin assets | Existing repository plugin surfaces | Same plus bounded explanation policy | Additive | hooks fail after packaging | plugin JSON + hook unit tests | **PASS** |
| `dw setup` fresh-machine install | Delegates to separate `idleproof` executable | Still delegates | No code change | core wheel alone cannot install native sidecar | no separately distributable `idleproof` artifact found in accessible repos | **BLOCKER for one-package fresh install** |
| `dw portal` fresh-machine sync | Proxy to separate `idleproof` executable | Still proxy | No code change | Portal onboarding command fails if sidecar absent | no separately distributable `idleproof` artifact found | **BLOCKER for full Portal rehearsal** |
| Public repository identity | Temporary `TFourniax/tooltest` | Still temporary | No | first public users pin wrong identity | `docs/RELEASE.md` explicitly requires final name | **BLOCKER for public tag, not internal testing** |
| Public Action pin | Examples can reference moving/temp identity | Release contract requires exact `v0.4.0a1` on final repo | Release-time | moving verification semantics | release checklist | **BLOCKER for public tag** |
| Personal UX/readability judgment | N/A | New richer explanations | New | technically correct but confusing | owner walkthrough | **HUMAN** |

## Release interpretation

A green automated matrix is necessary but not sufficient for the first public tag. The intended sequence is:

1. finish the installed-wheel IdleProof rehearsal on all supported OSes;
2. exercise actual Portal device enrollment -> ingest -> project explanation in one end-to-end gate;
3. make the `idleproof` sidecar/install story reproducible from a clean machine, or remove that hidden dependency by providing an equivalent packaged path;
4. rerun exact candidate matrices;
5. merge only the proven candidate into the canonical validation branches;
6. perform the owner's final human UX pass;
7. rename/move the public core to its final community-facing identity and update generated Action references;
8. only then merge/release/tag `v0.4.0a1` publicly.

No row marked **BLOCKER** should be converted to PASS based only on unit tests or documentation.
