# Change-envelope path admission

## Reproduced defects

The installed Core #119 product tree misreads Git's quoted line output as literal
file identities: accented names, tabs, line breaks and backslashes are transformed,
leading/trailing whitespace is stripped and long names are truncated. File facts
also follow the envelope's commit hints even when they do not describe the tree
pair that defines its stable change identity. An untrusted commit hint beginning
with `--output=` is interpreted by Git as an option and creates a local file; the
regression confines that demonstration to a disposable synthetic repository.

A 300-file change tries to append 300 relations and violates the existing 256
relation limit. A missing claimed tree can still receive file observations from
an unrelated available commit hint. These are reproduced failures, not hypothetical
findings. All ten final regression tests fail/error on the previous installed
wheel; the original seven-test discovery run is retained separately too.

## Correction

Read the two full hexadecimal tree identities with the existing bounded read-only
Git runner, verify their object types, then use a NUL-delimited tree diff. Commit
hints never enter the Git argument list. Disable replacement objects, external
diff/textconv, lazy fetch and prompts; preserve the existing no-renames semantics.
Names retain exact UTF-8 bytes, whitespace and control characters in JSON and file
identity hashes. Human context quotes them and escapes terminal/direction controls.

Admit complete names only, deterministically sorted, at most 256 relations, with
the existing 500-character label limit, a 512-byte JSON name bound and a 128 KiB
combined file/relation allocation. The original 256 KiB event admission limit
remains authoritative. Unrepresentable/oversize names and count/byte overflow are
omitted whole, with exact total, omitted count and reasons in the source event's
`changed_files_coverage`. Missing/non-hex tree identities produce explicit
`unavailable` coverage and no file observations. A present non-tree object or
Git execution/output/time-budget error rejects the import before any append.
The Git diff output limit is 1 MiB, each process at most 15 seconds and the whole
collection deadline 30 seconds. Exceeding this bound is an explicit rejection,
not a partial scan represented as complete.

The CLI result always reports coverage. Journal coverage is additive only for
incomplete observations, preserving ordinary complete historical event semantics.
The artifact profile validates exact coverage shape/counts and forbids observed
paths in an unavailable result. Advisory context warns whenever imported path
coverage is incomplete, including changes outside the selected retrieval rows.
No derived database schema, hash algorithm, Proof authority or cloud wire schema
changes. Old events without coverage metadata do not acquire a new completeness
claim. Full source details remain accessible through `dw state event`/`history`.

## Compatibility and limits

Same-tree re-verification remains idempotent when ephemeral commit hints change
or disappear, because file observations now follow the stable tree pair. The
existing immutable-journal rule remains: if an earlier event for that change has
different malformed/truncated path facts, re-import rejects the semantic conflict;
this patch never reseals, deletes or silently repairs historical records.

This is bounded local path admission, not full monorepo history coverage, refactor
inference, proof that unchanged paths are unaffected, or qualification of deployed
consumers. Omitted paths are not inferred to be unaffected. Source control names
may contain sensitive text: this local journal reader is not a redacted export.
The remaining coordinated gates, deployment parity and exact-candidate HUMAN
acceptance stay open. Automated evidence is MACHINE only.

## Validation

The ten new tests use byte-exact Git object plumbing so difficult names are tested
on Windows/macOS/Linux without relying on host-specific working-tree path rules.
They cover exact names/hashes, tree-versus-commit binding and ephemeral hints,
option injection, terminal-safe context, 300-file bounded admission, unsupported
UTF-8/oversize names, missing trees, UTF-8 byte bounds and atomic malformed-coverage
rejection. An eleventh installed CLI test imports a real 302-file envelope with
an option-like commit hint and checks exact bounded names, omission count and no
unexpected file write. It fails on the old wheel and passes on the candidate.

The fresh installed candidate wheel passes the full 704-test suite (52 explicit
platform/optional-provider skips) in 69.474 seconds; the subsequently added CLI
test and ten API tests pass together as an 11-test installed suite. No product
module changed between these runs. All four changed modules are byte-equal in
source, wheel and installation. Baseline failures, full suite and focused logs,
wheel/module hashes are retained in `evidence/CHANGE_PATHS_local.json` and its
referenced files. Exact PR/main qualification is tracked separately in registry #74.

Before merging, a compatibility probe found that an unknown unprofiled historical
extension could supply a list/object as coverage.status and crash context's set
membership check. The baseline regression retains that TypeError and a subsequent
SQLite lock error; the reader now uses a non-hashing comparison without changing
legacy journal admission. This twelfth regression joins the real installed CLI
test in the final full suite: 706 tests PASS, 52 explicit skips, 69.491 seconds.
The corrected wheel and all four module hashes are in `CHANGE_PATHS_final.json`,
along with the retained failure and lossless full-suite archive. Earlier successful
test runs do not qualify this later product or erase that discovered defect.
