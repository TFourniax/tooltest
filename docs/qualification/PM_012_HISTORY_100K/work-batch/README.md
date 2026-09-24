# PM012 Work batch — not qualified for merge

Base26f663b0d2fbecf779324a1f78f8359750787c63. Product changes are grouped locally:
compiled syntax validators, profile dispatch, alias-preserving JSON detachment,
bounded native JSON decode with exact per-line canonical equality and strict
fallback, reused lexical serialization and32MiB private SQLite bulk cache.
Every shape, profile, chain digest, dedupe and ordered-history validation still
runs. No persisted validation shortcut or weakened durability/budget.

Full local suite:746tests,52skips,one failure in the race-test failpoint because
its old helper is no longer called. The failpoint moved to actual event admission;
its original-byte digest and forged-byte refusal assertions remain. The corrected
255-test continuity suite passes in21.330s. New adversarial cases cover equal-count
cross-line JSON injection, duplicates, non-JSON whitespace, CR/LF framing,
legacy spelling, exact byte hashes and detached alias/cycle semantics.

100k still FAIL after the decoder change: append9.497201s<=10,
verify3.056519s>2,rebuild7.181036s>5,cold59.251ms<=1000,
hotp9562.611ms<=300. The earlier local grouped attempt was9.484181/3.978065/8.471478.
These are observations, not a controlled machine-speed comparison or budget PASS.
The separate cProfile run completed with unchanged72188837-byte journal,
SHA2565ad1faabbdf9a02b1ceaf6124563ca2275524fcf7fee11fd968f9b6e3c5c3e85.

Preserve this work on a non-PR branch while the failing budget is unresolved;
do not consume another hosted matrix solely to rediscover the known failure.
No latest-head independent review, installed final wheel, merge, HUMAN or Alpha
qualification is claimed for this batch. The original draftPR129 remains open.
