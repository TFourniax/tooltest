# PM-015: local cited questions

`dw ask "Why auth?"` retrieves recorded facts deterministically, builds a bounded
ContextPack, then presents only its extracts with exact original event IDs and
hashes. `dw --language fr ask "Pourquoi auth ?"` changes presentation, not facts.
Use `dw state event EVENT --hash SHA --json` to open an original cited assertion.
No model, network, command execution, query persistence or database rewrite is
part of answering. This is a working Core slice; coordinated IdleProof/Portal
interfaces and full semantic Q&A remain required for complete PM-015.

## Supported questions and conservative interpretation

- **Why / pourquoi:** recorded `why` or `reason` of matching active assertions.
  A recorded reason remains its original DECLARED/INFERRED/OBSERVED/VERIFIED
  assertion, not independently proven motivation or current code applicability.
- **What depends on / qu’est-ce qui dépend de:** incoming recorded `depends_on`,
  `imports` and `calls-name` relationships. Their declared or inferred status and
  original source remain visible. This does not infer every static/runtime
  dependency. An ambiguous outgoing-direction question abstains.
- **What changed / qu’est-ce qui a changé:** matching original `change.observed`
  events, original file coverage and exact tree identifiers where recorded.
  `since YYYY-MM-DD` / `depuis YYYY-MM-DD`, or explicit `--since`/`--until`, filter
  inclusive recorded instants in UTC. A date means midnight UTC; use a timestamp
  with timezone for another endpoint. Relative/ambiguous dates abstain. Timestamp
  text is not authenticated wall-clock evidence. Unparseable matching timestamps
  are counted and excluded rather than invented.
- Other questions retrieve matching current active recorded assertions; they
  are not a claim to understand an arbitrary natural-language question.

`--kind why|dependencies|changes|memory` selects interpretation explicitly;
`--entity ID` resolves an exact identity. Matching uses deterministic FR/EN lexical
normalization, never a translation claim. Responses reveal the chosen terms,
intent, direction, time bounds, match/omission counts and unknown semantic
completeness. An unknown topic or insufficient source yields `abstained`, not a
fabricated answer. No fact is made authoritative by being retrieved.

## Contract, persistence and bounds

JSON uses `memory-question-answer-1` containing `memory-question-context-1`.
The structural contract is `schema/memory-question-answer-1.schema.json`;
content hashes and exact source bindings remain semantic requirements.
The ContextPack binds the validated journal digest, count and head. Every fact
contains original source event/hash, journal sequence, timestamp, epistemic status,
category and extracted fields. Separate applicability citations identify lifecycle
judgments. Each answer part is only a ContextPack fact index plus its exact source;
there is no uncited generated factual text. Context and answer identities hash
their canonical content (excluding their own ID). `assurance` is always `none`,
`actions` empty and `questionStored` false.

The unchanged strict full-chain reader and ordered lifecycle validator admit one
coherent snapshot. Active memory comes from journal order, not timestamp sorting.
Dependencies select the latest recorded edge per directed triple and exclude
explicitly inactive endpoints. History uses original change records; it does not
rewrite them into current assertions. Questions are bounded to2000characters,
results1–50facts and ContextPacks1MiB. Oversized output fails explicitly; facts,
paths and citations are never silently shortened. The existing journal reader
still validates the complete history; 100k latency is not newly qualified here.

Human output quotes project text and escapes terminal controls and bidirectional
formatting. Questions, labels and reasons containing instructions remain data.
No source code, prompts, queries or raw events are uploaded to Portal by this path.
Existing journals need no migration and retain identical bytes. Older Core versions
simply lack this command; the event and certificate formats remain unchanged.

## Qualification

Before implementation the actual installed CLI rejected `ask`. Focused tests cover
FR/EN why/dependency/unknown queries, recorded-time offsets and ambiguity, retired
and confirmed assertions, literal identities, corruption, bounds, instruction-shaped
text and actual read-only CLI/help. The first implementation failed to combine a
natural since-date with explicit until; its failure is retained and corrected.
An initial relative PYTHONPATH also selected the previous installed package from a
temporary cwd; corrected qualification uses absolute source or an actual new wheel.

`scripts/memory_question_acceptance.py` uses the installed CLI to record declarations
and a relationship, ask six FR/EN questions, open each exact cited event, check JSON
language invariance and unchanged journal/state, then verify retirement abstention.
The existing installed-wheel jobs on all three OS run this journey. No new runner,
weakened assertion, external model or HUMAN qualification is introduced.

Remaining PM-015 scope: coordinated product entry points, richer recorded graph and
semantic retrieval, full temporal and adversarial corpus at project scale, plus the
authenticated long journey and named HUMAN acceptance. An extractive Core answer
does not establish the complete Alpha or replace these requirements.

Integrated mainc03164e:753tests PASS,52explicit skips,77.831s using a newly
installed wheel; six actual installed questions in both languages PASS, exact
sources opened and journal/state unchanged. The structural schema validates all
four answer categories plus abstention;15invalid authority/action/field examples
are rejected by a disposable validation dependency, not a new runtime dependency.
Initial schema tooling/path failures are retained. The earlier742test run is
provisional; only the later753test integrated run qualifies this source tuple.
Wheel/log hashes are retained; adding schema/docs requires fresh CI artifact IDs.
Final-head review, hosted gates and fresh main remain required.

Review4088785920/4088785929 exposed two unsafe interpretations. Incoming
questions now require an explicitly recognized incoming phrase in FR/EN; other
dependency wording abstains. A natural-language date is accepted only as a bare
terminal ISO date (optionally followed by punctuation). Attached times, including
ISO timestamps or “at noon”, abstain instead of becoming midnight. Explicit
--since/--until still accept complete ISO timestamps with timezone.

Regression-first head b21800c adds two journal-backed tests covering four outgoing
forms and four time-qualified date forms; existing hosted CI supplies before/after
execution because the Work cloud executor is offline. The installed-wheel journey
also exercises both errors in FR/EN. No assertion, source integrity rule or budget
is weakened. The original753local result applies only to the previous candidate;
this corrected candidate requires fresh hosted review/gates and fresh main.

Hosted BEFORE: run35941138786/job107449326048,755tests,7failures,52skips,
77.168s. Four outgoing forms and three time qualifiers return cited records when
abstention is required; the ISO-T form already abstains and remains covered.
Separate optional-provider job107449326392 fails hookp95166.7ms>150ms; retained
as a PM012 incident, not attributed to these question parsing changes.
