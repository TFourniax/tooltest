# Import existing Git history

`dw state bootstrap-git --max-commits 25 --json` retains the original first-parent
mode. Resume that mode with its returned `next_ref` and `--ref`.

`dw state bootstrap-git --all-branches --max-commits 25 --json` captures the locally
available HEAD, local branches and remote-tracking branches. It visits all parents
of those exact tips, including merged side branches and disconnected roots. Tags,
reflogs and unreachable objects are outside this scope. It does not fetch objects.
Ref enumeration is not an atomic multi-ref transaction; the returned tip IDs state
the captured scope and remain fixed for the continuation.

When `complete` is false, pass `next_cursor` to the same command with `--cursor`.
Keep `--include-messages` on every page if you explicitly opted in. Messages are
DECLARED statements, never executed Proof. Commit IDs, tree IDs and parent links
are observations of verified local Git objects, not authenticated authorship.
Each commit's changed files still describe its first-parent diff. Merge ancestry
does not itself establish runtime causality or rename identity.

Pages retain the existing default25/maximum100 commits,256KiB per commit,64 paths
per commit,4096 message characters,60-second collection and15-second Git command
limits. Capturing more than256 branch refs fails explicitly. Cursors are at most
64KiB; traversal output is at most16MiB with a one-million-row continuation-count
cap. Limit failures import no page. Neither source files nor author/email headers
are copied into history events; message text requires explicit opt-in.

Continuation checks both the captured traversal prefix and the corresponding
events in the byte-validated journal. A recalculated cursor checksum cannot skip
unimported commits or claim unimported messages. The checksum is a consistency
check, not authentication. Replaying a page is idempotent. Concurrent page imports
use the existing journal lock, admission and dedupe path.

Shallow or graft-rewritten parent lists are compared with raw commit headers and
reported as incomplete boundaries. After you deepen or repair the repository,
resume if the prefix remains consistent; otherwise restart idempotently. Git
version/order or topology changes can invalidate a cursor. Product commands do
not alter grafts, refs, the real Git index or working files to resolve a boundary.

Prefix replay costs O(history) per page. This is bounded pagination, not an
incremental graph store or a 50k/100k performance qualification. Exact supported
artifact and cross-platform gates are recorded with PM-003b; full longitudinal
identity, cited history retrieval and coordinated Alpha qualification remain in
the canonical registry.

## File relocation hypotheses

Add `--include-lineage` to import bounded file relocation assessments alongside
the existing commit observations. Only a unique removed/added pair of regular
files with exactly equal content and file mode produces a link. Both trees and
matched blob bytes are verified against their immutable object IDs. The link is
**INFERRED**: identical content cannot establish move intent. Existing file and
component IDs remain distinct; prior assertions and Proof never transfer.

```sh
dw state bootstrap-git --all-branches --include-lineage --max-commits 5 --json
dw state lineage --path src/old_name.py --limit 50 --json
```

The default view labels hypotheses in the selected language. `--json` returns direct old/new observations with their commit, source event ID
and event hash, in reverse journal order. It does not collapse branch histories
or infer a transitive identity. A missing link does not prove a file was never
moved. Copies, edited moves, mode changes and duplicate-content candidate groups
produce no inferred pair; unmatched and ambiguous counts remain explicit.
Unsupported names, symlinks and submodules are counted as excluded inventory.
`coverage.complete` concerns only the bounded regular-file inventory for this
assessment, not complete longitudinal identity or complete repository history.

Keep both requested opt-ins (`--include-lineage`, `--include-messages`) when
resuming. A lineage cursor uses version2 and requires corresponding assessments
in the byte-validated imported prefix; original no-lineage cursors remain version1.
Changing policy requires an idempotent restart. Importing lineage later adds
separate events, without replacing prior commit observations.

Each page permits at most32 pairs per commit,32768 expanded tree entries,512
unique trees,16MiB raw trees,64 tree levels,2MiB per matched blob and8MiB matched
blob bytes total. These are rejection limits, not measured monorepo capacity.
A limit failure appends no page; use a smaller page or leave lineage disabled.
No source content is persisted. The existing15-second command/60-second
collection limits apply. Read-only lineage queries strictly read the journal;
`--limit` bounds returned matches, not the cost of validating historical bytes.
Symbol/feature identity, edited moves and downstream applicability revalidation
remain separate canonical PM005/PM007 work.

The optional `project-memory-git-lineage-1` profile requires a Core build that
supports it. Older builds that do not recognize this profile reject the enriched
journal explicitly. Leaving lineage disabled preserves the existing history
event profiles; cursor version1 remains unchanged. Qualify exact tool artifacts
for consumers and rollback before enabling the new profile in a shared journal.
