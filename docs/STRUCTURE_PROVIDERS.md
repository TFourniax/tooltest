# Structural extraction contract

Core reads bounded, regular source blobs from one captured Git tree. A language
provider receives a repository-relative path and those bytes. It returns an
immutable `FileExtraction` with `schema_version = structure-extraction-1`, the
source SHA-256, provider/language identity, module, parse outcome and typed tuples
of symbols, imports and name-call references.

The coordinator validates every result before replacing the old projection. It
owns Git tree provenance, common component/symbol/edge identifiers and database
insertion. Providers cannot supply another path or digest, invalid source line
positions, mutable collections, or `VERIFIED`/`DECLARED` structural authority.
An unparsed source has no symbol/import/call claims. Its component still records
that the source file exists, and coverage explicitly remains incomplete.

The Python adapter uses the existing AST behavior: top-level functions/classes
and direct class methods are observed declarations; module imports are observed
syntax; name-based calls to a local top-level symbol remain inferred. This is not
runtime name resolution, a complete dependency graph, or an execution proof.
Existing IDs and Python import heuristics are preserved by this extraction split.

The contract stamp participates in index freshness. Changing its semantics must
invalidate that stamp; a missing or different version forces a refresh even when
the Git tree is unchanged. The event journal and authoritative Proof are unaffected.

Only the Python provider is wired into Core in this unit. Additional languages
and the adapter for IdleProof's working-tree feature heuristics remain tracked in
PM-004 of registry #74; a Git-tree result must never label dirty working bytes as
the committed source or upgrade heuristic findings to observed/proven facts.
