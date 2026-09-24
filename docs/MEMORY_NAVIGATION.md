# Find recorded reasons and inspect original history

Use an exact memory ID from `dw context`, `dw task show`, a declaration command or
`dw state graph`:

```sh
dw state why DEC-REFUND
dw state history DEC-REFUND --limit 20
dw state why DEC-REFUND --json
dw state event dwev_<24-hex-digits> --hash <full-event-hash> --json
```

`why` follows recorded relationships in both directions. It shows each assertion's
label, recorded reason, authority and exact source event ID/hash. An incoming
`motivated_by` or outgoing `affects` edge retains its original direction and its
own authority/source. Navigation never infers causality from proximity in the
graph. When a relation has been reasserted, navigation selects its latest recorded
version; `history` retains the older original events too.

`event` opens the original record directly by the ID in a citation. With `--hash`,
it also requires the complete cited SHA-256 to match; missing or mismatched sources
are rejected. This provides a direct way to inspect an incoming relationship's
source without paging through the source entity's complete history.

Retired/rejected/superseded memory remains visible as historical context. Its
original assertion and later applicability judgment have separate citations.
A referenced entity without its own journal assertion is explicitly unknown;
its label and authority are not copied from a neighboring node.

## Read the rest of a history

History pages contain original subject events, newest first. The result includes
`nextCursor` when more events remain:

```sh
dw state history DEC-REFUND --limit 20 --cursor '<nextCursor>' --json
```

The cursor binds the exact entity and an immutable journal prefix. Later appends
do not change the selected historical page set. Start without a cursor to include
new events. A truncated or divergent prefix invalidates the cursor and requires a
fresh first page. A cursor is a local pagination aid, not an authentication token.

The default page limit is 50 events, at most 200, with a 1 MiB compact JSON bound.
Events are kept whole; a byte-bound page can contain fewer events than requested.
Long reasons are explicitly shortened only in human-readable output; JSON history
retains the complete original event. Quoted text escapes terminal controls and
direction overrides rather than allowing recorded text to imitate CLI headings.

## Navigation bounds and evidence meaning

`why` defaults to depth 2, 50 nodes and 100 edges. Options `--depth`, `--max-nodes`
and `--max-edges` permit at most 4, 100 and 200 respectively. The JSON response is
bounded to 8 MiB. `coverage.truncated` marks omitted navigation caused by a bound.
The graph is deterministic and cycles cannot duplicate edges indefinitely.

These commands validate the complete existing journal once per invocation and
read its recorded relationships. They do not create or update a derived database,
append an event, execute project code, contact a provider or send data to Portal.
They expose local journal content; do not mistake them for a redacted cloud export.
The journal scan still scales with history size; output bounds are not a claim of
constant-time lookup.

Hashes establish the identity/integrity of journal records, not authenticated
authorship. Authority remains attached to its exact assertion. Historical Proof
and a human applicability judgment do not reverify today's code. Use the existing
`drift`, revalidation and exact-code verification commands for those questions.
This surface does not add unrecorded symbol/refactor lineage, reconcile divergent
writers or implement the separate Portal longitudinal store.

## Forward journal pages for incremental consumers

`dw state events --after N [--expect-head HASH] --limit L --json` returns
`project-event-page-1`: the validated journal in source order after the first `N`
events, at most `L` (1–500) whole events and 1 MiB. `journal.genesisHash` identifies
the journal, `next`/`head` form the next cursor. For `N > 0` the caller must present
the hash of event `N`; a truncated or divergently replaced prefix fails closed with
exit status 2 and asks the consumer to restart from event 0 instead of skipping.
Without `--after` the command output is unchanged.

Events are returned unchanged and include local payload text. Projection and
redaction belong to the consumer; IdleProof exports only its Portal allowlist.
