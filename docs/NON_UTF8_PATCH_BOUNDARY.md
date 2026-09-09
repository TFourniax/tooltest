# Textual patch encoding boundary (PR #57)

## Before implementation: chosen contract B

Owner review of bd888a659122a920441ae80a3b0ac26578a490f0 accepts the LF/CRLF correction but holds HUMAN retest. The independent reproduction in qualification/non-utf8-before.json shows distinct FF/FE bytes producing mutation ID `6886cdb539`, then real stable-fail/stable-pass/witnessed analysis followed by UnicodeEncodeError in build_report, write_json and reduction output. The CLI announces one analyzed mutation before failing to produce its certificate.

Choose explicit fail-closed support, not a general encoding redesign. Validate the complete textual Git diff before parsing, filtering, mutation identity or evidence execution. Unsupported surrogate-bearing text yields the stable reason `unsupported-text-encoding`, INCONCLUSIVE, with no new Proof/certificate/reduction artifact. Direct mutation identity construction also rejects unsupported text, so neither invalid-byte patch gets an ID. This is contract B's deliberate alternative to full-support distinct IDs. UTF-8 textual patches (including LF, CRLF, mixed endings and Unicode) retain exact supported bytes and existing IDs. Git binary patches with ASCII transport are unaffected.

| Input | Parse / mutation | Analysis / report | Reduction output |
| --- | --- | --- | --- |
| UTF-8 LF / CRLF / mixed | Accepted, exact bytes hashed | Existing semantics and canonical IDs | Exact UTF-8 bytes, no host newline conversion |
| Text containing FF / FE | Explicit unsupported-text-encoding; no ID | Not entered; no Proof | Not created |
| Incompatible supported patch | Accepted text | Existing apply-error / inconclusive | No relaxation |

Keep binary Git transport unchanged. Surrogateescape is an internal transport mechanism, not a promise of product support for arbitrary textual bytes. Do not change generic JSON canonicalization or replace invalid bytes. Validate reduction text before creating an output file as a defensive final boundary. All current normal entry points parse the diff first; directly constructing unsupported internal report models is outside this contract.

## Consumer / identity audit

`parse_file_patches` feeds CLI prove, frontend observation, Gate/adaptive, proof_cli task capture, ide_handoff, Debt and semantic redundancy. Reject before parsing even ignored files so unsupported input cannot silently disappear. `_mutation_id` is the patch identity primitive and currently uses lossy replacement; replace that with the same strict validation. Downstream adaptive dictionaries and mutation roles consume its IDs. Reporting, attestation, Gate, assurance and frontend JSON hashes retain strict UTF-8 canonicalization unchanged because unsupported patches no longer reach them. Semantic redundancy's source-text normalization and Debt's whole-file heuristic readers are distinct existing contracts; no encoding redesign of those heuristics is included.

Qualification must cover direct IDs, real committed CLI Proof with optional minimization/reduction, generated installed native hooks rejecting unsupported text, supported LF/CRLF journeys, valid-Unicode identity stability and incompatible patch rejection. The preserved human-failed Windows fixture remains untouched. A new machine-green SHA requires owner review before a fresh targeted HUMAN retest. No merge or Alpha tag.

## After implementation / local qualification

`qualification/non-utf8-after.json` captures the public CLI on the same committed Latin-1 fixture: exit 2, empty stdout, stable unsupported reason, no certificate or reduction file. Both invalid bytes raise ValueError before an ID exists. Targeted tests also assert analysis/report functions are never called, and a real supported UTF-8/CRLF proof persists readable UTF-8 JSON and an exact CRLF reduction delta. The installed consumer executes both generated providers' hooks: Stop blocks with strict JSON, no evidence command runs, no envelope/certificate is created, and user HEAD/index/hooks are preserved.

Local full suite: 344 tests PASS. ProofBench: 4/4 PASS. ContinuityBench 10k: PASS. Integrated Product Smoke: PASS. Local native consumer: both providers' unsupported-text rejection and four LF/CRLF accepted-Proof journeys PASS. Authoritative cross-platform run IDs and artifact digest will be recorded on the exact published candidate in PR #57, without a further source commit solely to insert its own hash.

Reviewed repair versus bd888a: only diffing.py and cli.py change product code. Complete product diff versus qualified main 4a53a9fd9f338b7deaa11ade26d02c933c86b6bf retains the unborn implementation and accepted byte transport fix; no additional provider payload/trust/executable resolution or Protect changes. No certificate schema/canonicalization change. The limitation remains explicit: full arbitrary non-UTF8 textual Proof is not supported.
