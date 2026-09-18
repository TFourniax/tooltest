# Initialize memory from existing Git history

Run `dw state bootstrap-git --json` in a repository to import up to 25 existing
commits from the captured HEAD, following each commit's first parent. The command
observes commit/tree/parent identities and changed paths, without reading dirty
source, modifying the index or creating Proof. Re-running it is idempotent.

The JSON result supplies `next_ref`. Continue with
`dw state bootstrap-git --ref <next_ref> --json` until `next_ref` is null.
Keep that returned immutable ref if HEAD changes between pages. Each page can
contain 1–100 commits using `--max-commits`; previously imported commits count
toward that page and do not create duplicate events.

Only commit-message digest/byte count is stored by default. If you explicitly
want the message text in local Project Memory, add `--include-messages`. It adds
separate DECLARED message entities, preserving existing OBSERVED commit metadata.
This can be done later by replaying the same pages. No author email/header is
copied. Imported message previews are at most 4,096 Unicode characters; truncation
is recorded. Non-UTF-8 messages are omitted with `messages_unreadable` reported.
Opted-in text becomes part of the local journal and any later explicit checkpoint
export; review its suitability before enabling that option.

`dw state events --json` and `dw state graph --json` expose the imported records.
They are historical artifacts, not native task participation or executed change
envelopes. A commit message claiming a successful test does not create a Proof.
No human acceptance, causal task link or inferred rationale is generated.

The importer follows first-parent history, retaining all parent IDs of merges
while comparing the merge to its first parent. It does not import every side
branch. At an unavailable parent (for example a shallow clone), it returns a
visible boundary and a ref to retry after deepening/repair. It does not reinterpret
the boundary commit as a root. `complete` describes first-parent traversal, not
complete path/message coverage or whole-project understanding.

Limits: 256 KiB per commit object, 64 paths per commit, bounded path names, 1 MiB
per diff-path output, 15 seconds per Git child and 60 seconds for page collection.
The omitted-path count is retained in each observation and the page result.
An oversized/invalid object or command output rejects the collected page before
append; it cannot silently produce a complete observation. Journal validation and
state reconstruction then use the existing integrity path and their existing
costs, outside the Git collection time budget. No source patches are imported.

Object replacements and lazy fetching are disabled. Diff extraction disables
external helpers/text conversion and uses NUL-delimited names. These switches
follow the [Git command documentation](https://git-scm.com/docs/git) and
[`diff-tree` documentation](https://git-scm.com/docs/git-diff-tree).

MACHINE qualification is recorded in the repository journal and registry #74.
HUMAN remains NOT RUN for this candidate; rename lineage and product history UI
have separate acceptance tasks.
