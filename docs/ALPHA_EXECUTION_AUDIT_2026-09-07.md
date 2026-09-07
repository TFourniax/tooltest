# Public Alpha execution audit — 2026-09-07

Status: pre-implementation audit; **not a release qualification report**.

## Verified repository state

| Repository | Exact main | Finding |
| --- | --- | --- |
| TFourniax/tooltest | `e9bf514a3f13b1fc4124e3ff6a0e416016a2790b` | Matches the frozen human baseline. All four exact-main workflows passed. |
| TFourniax/idleproof-portal | `37604de43fd82b53a38b8cead17124cb58a247de` | Two documentation-only commits after product baseline `59af36ec6ea9e19e63a1b70bc517dfc073d529f0`; do not reset. |
| TFourniax/diffwitness-private | `d63710bde19be383526a1a315d49f6bb6212e8ff` | Initial README only. Implementation remains in draft PR #1; main is not the engine release candidate. |

Core refs/tags were fetched. Private repository metadata, trees, diffs and CI were read using authenticated GitHub access; private Git transport was unavailable in this execution environment. No private ref or product code was changed. The available local Portal source matches every blob in current main except the two new commercial documents, which were read from GitHub. This is source comparison, not a claim of a successful private fetch.

Core CI evidence: [test](https://github.com/TFourniax/tooltest/actions/runs/33896211060), [ProofBench](https://github.com/TFourniax/tooltest/actions/runs/33896211095), [ContinuityBench](https://github.com/TFourniax/tooltest/actions/runs/33896211039), [Integrated Product Smoke](https://github.com/TFourniax/tooltest/actions/runs/33896211042).

Portal [run 34118513878](https://github.com/TFourniax/idleproof-portal/actions/runs/34118513878) passed app Node 22/24, Deno 2 and database replay. It does not establish current browser, managed runtime, human or paid-flow qualification.

No open core or Portal PR was returned by the scoped search. Private PR #1 remains draft with explicit value/distribution/entitlement gates. Both main branches report `protected=false`.

The separate `TFourniax/tooltest-2` repository remains an integration dependency: its main is initial commit `6398a5416455aaab2713dcb7f9409a9d77a4b3a2`, while the branch pinned by Integrated Product Smoke is at `49c4daa04088e3ba270e9e97810dd40e48bad29b`. A standalone canonical desktop repository was not established by the repository search; existing local web UI assets must not be claimed as a qualified distributed desktop app.

## Evidence and conflicts

Read issue [#52](https://github.com/TFourniax/tooltest/issues/52), including all seven comments. Its body still says Codex Protect needs human testing, but later CP-01 through CP-05 comments establish HUMAN PASS. The later evidence takes precedence; preserve the original record.

Reviewed core product surfaces, Protect, Proof protocol, Debt, inference, threat model, release and existing workflow/test contracts. Reviewed Portal product surfaces, readiness/requirements, managed AI operations, self-hosted CI, canonical commercial blueprint and delta roadmap.

Conflicts resolved for execution scope:

- `docs/PROTECT.md` still foregrounds `dw guard`; native provider use is the qualified happy path. The wrapper is an explicit fallback.
- Historical release docs name `TFourniax/diffwitness`; the newer canonical commercial roadmap requires a Lab identity. Do not invent the Lab account or rename repositories during a correctness fix.
- Requirement Matrix, Trust Graph, Registry and longitudinal intelligence are high-priority post/parallel commercial expansion in roadmap section 6. They are not all immediate public OSS blockers. Publicly sold capabilities require complete server enforcement and paid-flow qualification.
- The uploaded execution contract asks for audit first, then small phases. This change starts with HT-009, rather than combining trust-state repair, unborn repository identity, localization and commercial schema changes into one candidate.

## Gap and risk assessment

| Area | Evidence/status | Next work / regression risk |
| --- | --- | --- |
| Native Windows Proof + Protect | Human baseline passes Claude and Codex; see frozen manifest | Preserve hook commands, payload parsing, strict JSON, provider trust, exact-tree coverage; high risk |
| HT-009 | Reproduced on baseline: enable → observe → disable → re-enable reports `requires-provider-feature-and-trust` despite no provider trust evidence | Separate unknown provider trust from missing local observation; first phase |
| HT-005 / HT-012 | `status.setup.native_ready` and doctor native readiness use setup scope, not actual installation/runtime state | Separate configured/installed/observed and verification readiness; subsequent phase |
| HT-013 / HT-014 | Reproduced fresh `git init` + `dw setup --agent claude --json`: exit 2, `git rev-list ... HEAD` | Explicit unborn local identity and first-commit transition, without changing established lineage fingerprints |
| HT-003 / LANG-001 | Guided strings are hardcoded French; Technical can include French provider rows | Deliberate English-default, explicit-French presentation system; JSON unchanged |
| Project understanding/value | Existing status, Debt, Continuity and inference primitives present | Shared read projection and representative longitudinal value qualification remain unqualified |
| Portal commercial | Bounded storage, RLS, enrollment, quotas and audit foundations present | Requalify current candidate; entitlements v2 and full billing for sold plans; export coverage |
| Desktop/distribution | Core wheel/binary/Action gates present; standalone desktop not established | Audit actual deliverables and coexistence, no unsupported desktop claim |
| Performance/security | Existing benches/threat model; no new cross-platform measurements | Profile after state correctness; full threat/consumer review remains open |
| Release identity/governance | Both main branches unprotected; temporary public name | Prepare migration preserving issues/PR/evidence; operator identity/legal decisions and exact canonical gates remain required |

Open issue labels are not independent reproduction evidence. The table distinguishes reproduction, source findings and unqualified work. There is no claim of zero P0/P1 or Alpha completion.

## Phase 1 — HT-009

1. Freeze behavioral references in `QUALIFIED_BASELINE.md` before code changes.
2. Replace unsupported claims of pending Codex approval with unknown trust and awaiting local observation. Keep readiness conservative and provider-owned trust untouched.
3. Cover disable/re-enable, unchanged hooks, native hook preservation, safe activation, both views and no false Proof promotion.
4. Run targeted tests, full tests, ProofBench, ContinuityBench, Integrated Product Smoke and packaging gates on the candidate.
5. Require provider-real Windows Codex qualification before merge; record exact SHA, provider version, commands and evidence. No public tag.

Later Alpha phases remain open; passing this phase does not close the other rows above.
