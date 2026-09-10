# DiffWitness pre-alpha — active release-readiness registry

Updated: 2026-09-10

This document is the **active-only** release queue. Historical qualification evidence remains in GitHub issue #52 and the relevant PRs; completed HT items are intentionally not repeated here.

## Current coordinated baselines

- Core `TFourniax/tooltest`: `main` = `176b3d921038aa154ecc55b09ea33d57f0db875e`
- Portal `TFourniax/idleproof-portal`: `main` = `18d6b98c9fb7fcb430f71db568a72dd381c4789d`
- IdleProof companion `TFourniax/tooltest-2`: product candidate branch = `agent/prealpha-p0-hardening-20260823`; current pre-review base = `49c4daa04088e3ba270e9e97810dd40e48bad29b`; correction PR #3 is not approved yet.
- Private engine `TFourniax/diffwitness-private`: product candidate remains on draft PR #1 / `agent/private-engine-v1`; `main` is not the product candidate.

## Active queue

| ID | Area | Status | Blocking condition / exit gate |
| --- | --- | --- | --- |
| RR-001 | Core Windows subprocess text decoding — issue #69 | IN PROGRESS | Deterministic RED, bounded fix, full 21-job matrix + ProofBench + ContinuityBench + Integrated Product Smoke, exact-main post-merge qualification. |
| RR-002 | IdleProof auth concept precision/recall — PR #3 | BLOCKED IN REVIEW | Restore real identifier recall without arbitrary-substring false positives; complete 13-job matrix on replacement exact SHA; independent re-review. |
| RR-003 | IdleProof coordinated RC provenance / PR #2 | BLOCKED BY RR-002 | Freeze one exact final companion artifact, preserve historical HUMAN evidence without transferring it to another SHA, then perform only the acceptance required by the final delta. |
| RR-004 | Private Engine release-contract closure — PR #1 | TODO | Close real-repository value gate, exact private artifact install/update/revoke/rollback operations, and entitlement/licensing semantics without weakening public Proof authority. |
| RR-005 | Coordinated Portal release gate audit | TODO | Re-audit current Portal main against app/Edge/DB/browser tenant-isolation, ingest idempotency, revoke/rotate, roles, export/deletion, entitlement and production-deployment requirements; create bounded findings for any real gap. |
| RR-006 | Public distribution / release provenance | TODO | Freeze exact coordinated Core/IdleProof/Portal/Private versions and verify install/action references, tags/releases, rollback artifacts and upgrade paths before publishing any pre-alpha. |
| RR-007 | Consolidated security + defined-user-needs release audit | TODO | No known P0/P1 in the defined threat model; all defined user journeys mapped to executable evidence; performance/privacy/failure-mode gates green on the exact coordinated artifact set. |

## Regression rule

1. Every implementation task begins from an exact qualified baseline and reproduces the defect before product code changes.
2. A task is not closed on aggregate CI alone: inspect the relevant individual jobs and exact SHA/tree.
3. A previously qualified HUMAN surface is frozen. It may only be modified after a newly reproduced finding demonstrates a defect on that surface and the required human requalification boundary is explicitly defined.
4. If work on task A causes a regression in a previously qualified task B, create/journal a new regression finding linked to A and B. Task A cannot be promoted until that regression is corrected and B's durable acceptance gate passes again.
5. Machine PASS, HUMAN PASS and exact-main post-merge PASS are distinct claims and must never be conflated.
6. No public pre-alpha release while a reproducible P0/P1, release-provenance blocker, privacy/tenant-isolation blocker, or required user-journey gap remains.

## Release-ready definition

Pre-alpha release-ready means the exact coordinated artifact set is fully installable and usable for the defined tech/non-tech journeys; Proof/Protect/Debt/Continuity/understanding boundaries remain truthful; raw source/prompt/diff privacy defaults are preserved; supported failure/recovery paths are deterministic; performance budgets hold on supported platforms; and there are **no known P0/P1 vulnerabilities or correctness blockers in the defined threat model**. It does not mean an absolute guarantee that no vulnerability exists.
