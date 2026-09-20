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
