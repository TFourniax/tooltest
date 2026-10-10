# Captured project structure: public ecosystem contract

`dw state structure` is a new local scan surface. It reuses Core's source admission,
language providers, component IDs and conservative import resolver. It does not
read the private engine, execute the project, install dependencies, run hooks,
fetch lazy Git objects, create Proof or measure/admit debt. It writes only its own
derived capture/cache under the repository's Git metadata. `state graph` remains
memory navigation; `state rebuild` remains a separate writing operation.

## CLI and resumable work

Run from a Git repository, or pass `--repo PATH` on every command:

```sh
dw state structure start --source HEAD --document README.md --ci --json
dw state structure step --snapshot dwscan_<64-hex> --batch 32 --json
dw state structure status --snapshot dwscan_<64-hex> --json
dw state structure cancel --snapshot dwscan_<64-hex> --json
dw state structure resume --snapshot dwscan_<64-hex> --json
dw state structure page --snapshot dwscan_<64-hex> --limit 50 --json
dw state structure page --snapshot dwscan_<64-hex> --cursor '<nextCursor>' --json
dw state structure source --snapshot dwscan_<64-hex> --path module.py --line 1 --limit 40 --json
```

Use the ID returned by `start`, repeat `step` until `state=complete`, then page.
`cancel` pauses extraction; `resume` continues the same captured bytes, even after
process exit. Capture is one bounded atomic phase; interruption during capture
requires a new start. Cancellation cannot interrupt a filesystem syscall or an
already running bounded batch. There is no worker in the native hook path.

## Scope, safety and budgets

HEAD captures a fixed tree; a later commit cannot change its pages. WORKTREE is a
separate capture with `tree=null` and an optional committed `baseTree`. Two complete
bounded inventories and per-file identity checks must agree. A mutation rejects
capture and explicitly requires restart. Symlinks/reparse points are not sources;
POSIX descriptor-relative no-follow reads and Windows final-handle path checks
guard source reads. Git symlinks and submodules are never followed.

Tracked credentials, `.env` variants, hidden paths, downloaded dependencies,
caches, builds, generated files and binaries remain excluded. Selected documents
do not bypass these exclusions. `--ci` admits only `.github/workflows/*.yml|yaml`.
No network request or runtime resolver participates. File roles are path-based
INFERRED classifications; an SQL suffix does not prove a deployed database.

Limits: 20,000 inventory entries; WORKTREE also counts traversed directories
against that budget. Excluded directory contents are not enumerated. Git manifest
output is limited to 8 MiB and fails closed above it. At most 2,000 admitted files
(`--max-files` may lower this), 1 MiB/file, 32 MiB/source capture, 64 explicitly
selected documents. Steps default to 32 files, at most 64. Pages contain at most
100 rows / 2 MiB, with relation omissions reported. Source excerpts contain at
most 100 lines / 2,000 characters per line, with truncation flags.

The inventory denominator is incomplete when enumeration stops. Paging all rows
does not repair it. `coverage` separately exposes eligible, attempted reads,
captured sources, statuses, reasons, reuse and limits. `complete` is not human
mastery, runtime coverage or requirement fulfillment. Missing optional pinned
grammars are `unparsed`; an unsupported extension is `unsupported`.

## Identity, schema and consumers

Headers use `structure-snapshot-1`; pages add `structure-page-1`. Source excerpts
use `structure-source-1`. Page rows reuse `structure-extraction-1` facts with a
source-bound `description`, versioned here as `structure-extraction-2`. The
independent byte transport `state extract` keeps its existing version and limits.
See `schema/structure-page-1.schema.json` and IdleProof's `validateScanPage`.

Snapshot identity binds captured source/path/mode manifest, source kind, selection
and inventory/provider profile. Identical-content commits reuse a snapshot;
capture time remains the original observation time. Facts are cached by exact
path, role, source hash and profile. A profile/language/configuration/content
change invalidates affected facts; a removed file cannot retain outgoing links
in the new frame. Earlier immutable frames remain readable. Exact paths are never
case-folded or normalized into aliases. The snapshot's `resultSha256` binds final
coverage rows and triage; each extraction has its own digest.

Every page must have identical identity, profile, selection, capture time,
coverage and result digest. Consumers verify types, authority, source digests,
component IDs, offsets/cursors, uniqueness and resolved-target scope. They must
reject a mixed or corrupt stream, rather than publish a partial success.

## Meaning and limits of the map

Declarations, conditions, returns/raises and literal imports are OBSERVED syntax.
Resolved imports, path roles and route/decorator candidates are INFERRED. An
ambiguous import stays unresolved. Test imports nominate tests; they are not
executed coverage. Selected owner documents are DECLARED intentions. Literal
expressions are preserved locally so differing rules/thresholds remain inspectable.
Missing intent, runtime dispatch and correctness stay UNKNOWN.

Advisory responsibility triage reuses the existing redundancy sensor's token and
similarity primitives, without its ledger admission. It preserves differing
literals/conditions and source spans. Bounds: 100 parsed production files,
128 KiB/file, 500 units, 2,000 pairs, 20 findings, a three-second cooperative
budget checked between files/pairs. One bounded parser operation may finish after
that deadline. Omitted work is explicit. Similarity never establishes equivalence,
unused code, a deletion recommendation or a measured debt obligation.

## Qualification

`tests/test_structure_scan.py` uses fresh disposable repositories for snapshots,
mutation, exclusions, source integrity, paging, cancellation, cache invalidation,
directory fanout and review candidates. Optional-provider tests run separately
with the exact `structure` extra. Windows fixture symlink creation may be skipped
when unavailable; that skip is not a cross-platform security PASS. Integrated
Local/Portal and HUMAN results belong to their exact coordinated version set.
