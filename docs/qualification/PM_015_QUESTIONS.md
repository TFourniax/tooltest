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

Review4088833583/4088833589 found compound-direction and mixed CLI/question
constraints. BEFORE79b6d77 run35941905285/job107451753320 executes757tests:
9subcase failures,52skips,93.576s. Its complete log is retained. The first-round
fix had already passed755tests on Linux job107450310955; that does not cover the
newly found cases.

The incoming target now rejects conjunctions, embedded questions and further
dependency clauses. Temporal language is inspected independently of CLI flags;
unsupported relative/qualified bounds abstain. A supported bare since/depuis date
must agree exactly with an explicit lower bound. Other CLI bounds never erase
question-side constraints. Both regressions also run in the installed journey.
No local execution after these changes is claimed while Work cloud is offline;
final hosted review, all gates and fresh main remain required.

Review4088878860/4088878864/4088878867 found mixed question intents,
unsupported relative-time vocabulary and UTC normalization overflow. Regression
head 387f29ba61b3cada79f3cfefb9d3634c3f08d73a ran760tests with27subcase failures/52skips
in96.172s on35942676200/job107454105885. The full BEFORE log is retained.
Mixed supported intent families now abstain before precedence or an explicit kind
can discard a clause. Unsupported relative time and numeric slash/dot dates are
rejected independently of CLI flags; the finite lexical reader does not claim
complete natural-language understanding. Time words that are also names may
conservatively abstain. Datetime UTC overflow becomes a bounded ValueError and
normal CLI status2, with no traceback. Installed FR/EN journey exercises these
cases. Final hosted AFTER gates and review remain required; no local after-run
is claimed while Work is offline.

Review4088930520 identified relative-time qualifiers outside changes. The earlier
condition inspected the vocabulary only for changes or explicit date markers.
Regression-first0256d8f/35943477282/job107456578069 (Ubuntu/Python3.13)
runs761tests with5subcase failures/52skips in89.567s. Its original log is retained.
The condition is removed so the same temporal policy applies to why, incoming
dependencies and memory queries too. Five corresponding installed FR/EN cases
are added. The prior760-test Linux after-result is retained separately and does
not qualify this final change. Final hosted gates/review and freshmain required.

Review4088979869 exposed partial-word false positives for multiword dependency
targets. The same risk also affected why and changes. Regression-first9836b01
runs765tests with9subcase failures/52skips in94.398s on35944338885/
job107459127110. The complete BEFORE log is retained.
Retrieval now requires every meaningful normalized query term, with explicit
French/English grammatical stop words; partial overlaps no longer suffice.
Dependencies resolve the parsed target before selecting edges. Multiple matching
active identities abstain, including a matching identity without an incoming edge;
--entity provides literal disambiguation. Unknown relation targets are considered
without inventing current state.
The installed journey includes a payment-service distractor, precise auth-service
selection, a genuinely ambiguous auth query and recovery by literal identity.
Instruction-shaped queries with unmatched content abstain; a separate plain query
still proves exact malicious recorded text is quoted as data, citations remain
original and files/index/journal remain unchanged. This strengthens rather than
removes the instruction/data boundary test. The lexical reader still makes no
claim of full natural-language or semantic coverage. Final hosted gates, review
and freshmain are required; no local execution is claimed while Work is offline.

Review4089040597 identified a lost edge after resolving an unknown target:
a relation occurrence with no optional label was re-matched and excluded.
BEFORE0ef45aca/35944993411/job107461154943 runs766tests with2subcase failures/
52skips in84.645s. Both French and English queries returned SRC-A only, losing
SRC-B to the same OPAQUE-TARGET. The original log is retained.
After unique identity resolution, every active incoming edge to that identity is
selected without requiring a repeated optional label. The regression also keeps
an inactive source and unrelated target excluded, checks both original hashes
and exact coverage counts. The installed journey adds an import-shaped fixture
through the installed event API, then real CLI questions and source opening in
both languages. These synthetic fixture declarations are not a native producer
or HUMAN qualification. Final hosted review/gates and freshmain remain required.

Review4089081719 found that an inactive source could still supply a label during
unknown-target resolution, or create false ambiguity against a valid active
target. BEFOREcf60210d/35945699625/job107463343422 runs768tests with4subcase
failures/52skips in92.329s. Both false resolution and false ambiguity are
reproduced in French and English; literal identity recovery is retained.
One active-endpoint edge set is now shared by target resolution and selection.
An inactive edge cannot supply a usable label or a competing identity. Current
active assertion names still resolve targets independently of incoming edges.
The installed import-shaped fixture covers inactive competing labels, inactive
sole labels and literal-ID recovery; every returned source is opened exactly.
No authority or source assertion was relaxed. Original BEFORE and preceding
766-test AFTER logs are retained. Final hosted review/gates and freshmain are
still required; no local execution after the Work failure is claimed.

A complete review-thread audit found12findings, not11: earlier4088979861
(from <year>) was still open. The later all-term matcher did not fix the case
where a2025event contains auth/2026/service.py. Regression-firstb2bceda9/
35946613080/job107466121402 executes769tests with3subcase failures/52skips
in96.739s, with no CLI bound, an explicit upper bound and an explicit lower bound.
The existing French guard remains covered. Complete BEFORE and the preceding
768-test Linux AFTER logs are retained; the earlier clean review alone did not
close this missing case and no merge occurred.
Year-only from bounds now abstain under the same unsupported-time policy.
The actual installed journey includes the misleading-year path in a synthetic
older event and asks through the real CLI in both languages, including mixed
CLI bounds. Final-head distinct review, every hosted gate and freshmain are
required. Work remains offline; there is no local AFTER or HUMAN claim.

The thirteenth finding 4089181415 identifies ignored quarter qualifiers. The
regression-first head 579b61e25ccaf7176d7c432c0fd532e8e407039d runs 772 tests
with 14 subcase failures / 52 skips in 101.083s in 35947674667 / job107469404895.
Quarter/year expressions, short/version identifiers and non-Latin names expose
the underlying reuse of the broad context tokenizer, which drops short terms.
The complete BEFORE and preceding 769-test Linux AFTER logs are retained.
Q&A now keeps short and Unicode terms for strict matching, without changing the
general search index. Unsupported quarters, half-years and standalone years
abstain, including compatibility Unicode forms. Complete ISO date bounds keep
their existing behavior; literal --entity remains available for exact IDs.
The real installed CLI journey covers quarter/year abstention and exact short,
version and Unicode target selection in both presentation languages, opens every
returned source, and checks unchanged journal/state bytes. No schema, original
citation or authority assertion is weakened. Final-head distinct review, all
hosted gates and fresh main remain required. Work is offline; no local AFTER or
HUMAN result is claimed.

Latest-head review of ef0b937 raises findings 4089288605 and 4089288609:
C++ must not retrieve a C# runtime reason, and compact fiscal/quarter periods
must not select old events whose paths contain those period strings. Two
journal-backed regressions are added before correction. All 15 findings remain
tracked; the prior 772-test PASS does not discharge these new cases.

Regression-first 272d467f16d026736b285995e8f9bb83b34a9c78, run35949081790 /
Ubuntu3.13 job107473617511: 774 tests, 19 failures, 52 skips, 101.398s.
The original full log and preceding 772-test Linux AFTER are retained.
Question tokens now keep adjacent +/# qualifiers, distinguishing C++, C#, F#
and C. Unsupported compact fiscal/quarter/half-year forms abstain; four-digit
sequences outside the supported full ISO date are conservatively rejected even
inside words. Literal --entity with a generic question remains available for
such exact identifiers. The installed bilingual CLI checks exact technology
selection and compact-period abstention, retaining all existing byte/source
assertions. Final-head review, all hosted gates and fresh main are pending.
No local AFTER while Work is offline; no HUMAN execution claimed.

Review of aa749a8 raises findings4089335578/4089335580: import/call questions
must not fall back to lexical memory, and clock qualifiers must not select old
events whose path components happen to match. Two journal-backed regressions
precede correction. All17 findings are tracked; prior774-test PASS remains
historical, not qualification of these cases.

Regression-first b59d6a1af24f2571c7abbfc72144beba007c0a2a / run35949816851 /
Ubuntu3.11 job107476062725: 776 tests,18 failures,52 skips,91.746s.
Full original BEFORE and preceding774-test Linux AFTER logs are retained.
Import/call vocabulary now selects dependency intent and reaches the unsupported
direction guard. More generally, auto no longer silently falls back to memory
when no supported intent exists: it abstains. Explicit --kind memory or a
Memory/Mémoire/Remember request retains lexical lookup; a new additional
regression and real installed bilingual cases cover that documented behavior.
Clock-only qualifiers (colon, AM/PM, French hours, bare at/vers hours and zones)
abstain independently of CLI bounds. Existing full ISO date behavior remains.
Public README and CLI help explain the explicit lookup. All original authority,
citation and immutability assertions remain. All17findings, latest-head review,
hosted gates and fresh main remain required. No local AFTER or HUMAN claim.

Review finding4089390630 adds word-number clocks: numeric-only recognition
still lets three PM select a matching old path. A regression-first journal
covers word clocks, AM/PM spelling, o'clock and unsupported at/vers constraints
with and without CLI bounds. All18findings remain tracked; previous777-test
PASS is historical and no merge occurred.

Regression-first d41ab23a87d4bb451bbdd60b83fbf206da63e0a6 / run35950623623 /
Ubuntu3.11 job107478446977 runs778tests with18failures/52skips in96.024s.
Full BEFORE and preceding777-test Linux AFTER logs are retained.
AM/PM markers are now detected independently of numeric hour spelling. Compact
English/French word-hour suffixes and o'clock are recognized too. Unsupported
at/vers clauses abstain regardless of whether the following bound is numeric.
This is deliberately conservative when a time marker is also a name; use an
exact --entity with a generic question for that identity. The installed bilingual
journey repeats every new phrase with exact misleading-path fixtures while
retaining journal/state byte invariance. Final-head review, every gate and fresh
main remain required. No local AFTER or HUMAN execution is claimed.

Review4089471249 finds omitted weekend/season qualifiers. The next
regression-first test covers common English/French weekends, seasons, longer
periods and current work periods against old matching paths, with and without
CLI bounds. All19findings remain tracked; previous778-test PASS is historical.

Regression-first2d8af7a017b0ee39e3c83b5338279b0b7a3c0c3c / run35951481018 /
Ubuntu3.11 job107481006775:779tests,38failures,52skips,97.622s. Existing
week-end/semaine spellings already abstained; the38 failures reproduce the
omitted forms. The complete log and previous778-test Linux AFTER are retained.
The detector now handles weekends, longer periods and qualified seasonal/work
periods in EN/FR. A season name alone is not automatically a period: additional
positive controls retain Why Spring? and incoming Spring dependencies with exact
sources. Named from/during/pendant/durant bounds remain unsupported and abstain;
additional unit/installed cases cover these and separated/apostrophe fiscal-year
spellings. These extra cases are not misrepresented as part of the prior779-test
BEFORE run. The installed CLI uses old matching-path fixtures for every relative
period and preserves every source/authority/journal/state assertion. All19review
findings, final-head review, hosted gates and fresh main remain required. No
local AFTER while Work is offline and no HUMAN execution is claimed.

Latest review adds findings4089587924/4089587933 (21total): grammatical intent
must not be inferred from entity-name tokens, and numeric technology/compound
identifiers must not be interpreted as year substrings. Three regression-first
tests cover why, explicit memory and incoming dependency queries with competing
intent-word names, plus ISO/RFC/CVE/version identifiers. The correction must
retain all earlier mixed-intent, period and compact-year refusal guarantees.

Regression-first06bd1a404e3ded2e59c50600b54803b10848bcda / run35952701891 /
Ubuntu3.13 job107484590576:784tests,30failures,52skips,79.254s. Full original
BEFORE and preceding781-test Linux AFTER logs are retained. Supported leading
question forms now determine intent; clause forms retain mixed-question checks.
Only recognized grammatical prefixes/suffixes are removed from the entity phrase.
The global stop-word filter is removed, so change/memory/call/dependency names
and single-letter names remain distinguishing query data. Explicit --kind memory
keeps the entire label query; temporal guards still apply. Incoming target words
are retained completely. Unknown auto forms still abstain, and unsupported
outgoing forms retain their direction guard.
Unqualified years are standalone numeric tokens, not substrings of ISO/RFC/CVE/
version identifiers. Compact fiscal/quarter/half-year forms retain explicit
recognition, including four-digit year-first forms. The real installed bilingual
journey covers competing names, literal memory, dependencies, numeric names and
exact citation opening. An additional single-letter A control is not claimed in
the prior BEFORE. All original mixed/time/authority/source/immutability controls
remain. All21findings, fresh review, every hosted gate and fresh main are required.
Work remains offline; no local AFTER or HUMAN claim.


Review findings4089734559/4089734563/4089734565 bring the tracked total to24.
Regression-first e2a6918feddc326a7a2697e7a5be816ac72e25c9, tree
e16efb5aab6945066a4b17e365ef127554fc6f15 / run35954010148 /
Ubuntu3.11 job107488500201:788tests,26failures,52skips,82.130s.
Full original BEFORE retained; the explicit dotted-date negative controls already
passed, as did the underscore-embedded identifier and some conjunction forms.
Conjunctions now split intents only before an interrogative clause; a bare
memory/change/call suffix is part of the name. Incoming dependencies also retain
conjunctions while rejecting embedded question/dependency clauses.
Dotted software versions are lexical terms without a temporal introducer;
on/le dotted dates and all existing explicit/relative time guards still abstain.
ISO-looking substrings attached to identifier punctuation/letters remain data;
standalone dates retain the original ambiguity policy and since/depuis handling.
The real installed bilingual journey adds every new name, exact source opening,
conjunctive dependencies, and misleading old paths for the dotted-date controls.
All previous mixed-intent/direction/time/source/authority/immutability assertions
remain. Final-head distinct review, all hosted gates and fresh main required.
No local AFTER while Work is offline; no HUMAN or full PM015/Alpha claim.

Before final qualification, inspection found that the new identifier boundary also
blocked a sentence-final period after an otherwise supported ISO bound. The
right boundary now distinguishes a terminal period from a dotted identifier
suffix. An additional six-case EN/FR ?/./! exact-source regression covers this;
it is not attributed to the prior788-test BEFORE run. Latest-head review and all
gates must run again on this correction. No local execution claimed.


Hosted c1a6948 /35954423851: Ubuntu3.11 job107489877319 completes789tests
PASS/52skips/96.799s. The installed Ubuntu job107489877175 FAILS an unchanged
exact-ID assertion because the newly added conjunctive labels include an older
query's whole label (memory management/risk and memory management). Lexical
matching can legitimately return both; dependency lookup would be ambiguous.
The new installed fixtures now use a distinct retention suffix, retaining every
conjunction/intent-word case and all original exact-ID/source/byte assertions.
The unit regressions retain the original review labels in their isolated journal.
The assertion now includes synthetic question/flags/facts for diagnosis; its
condition is unchanged. Full failing installed log and789-test unit log retained.
Latest-head review and all hosted gates remain required; no local AFTER claimed.


Findings4089850123/4089850128/4089873151/4089873155 bring the total to28.
The earlier791-test BEFORE is retained. Expanded BEFOREe0d5042 /
run35955247101 / Ubuntu3.11 job107492183042 executes794tests with49failures,
52skips,101.145s. The complete original log is retained.
Partial standalone ISO months/weeks abstain. Unsupported on/le clauses are
recognized in the parsed target phrase, preserving grammatical depends-on.
Import/depend words alone remain name data; embedded dependency/question
clauses remain rejected before target resolution.
Recognized clause occurrences are counted before deduplicating intent families.
Repeated why/change/memory clauses abstain even with --entity. Compound
dependencies retain their existing direction-ambiguity refusal and reason.
Explicit bounds are tested against None, so empty strings reach normal bounded
ISO validation rather than silently removing a requested constraint.
The real installed bilingual journey adds all name/period/repeated-clause cases
and empty-bound exit2/no-output/no-traceback checks. Original exact source,
journal/state byte, authority, direction, version and mixed-intent assertions
remain. Final-head review, all hosted gates and fresh main are mandatory.
Work remains unavailable; no local AFTER or HUMAN/Alpha claim.


Findings4089948783/4089948792 bring the tracked total to30: omitted relative
phrases and colon-separated supported clauses. A separate root-cause regression
also prevents literal identity selection from discarding unmatched query terms.
BEFORE3fb8ddbe6706380c5e88a16395483ec9fc45616c /35956039183 /
Ubuntu3.11 job107494729797: 797tests,44failures,52skips,96.844s.
The complete BEFORE and preceding installed AFTER log are retained.
The temporal guard includes the tested EN/FR relative expressions and compact
to-date abbreviations. A colon separates clauses only before a recognized
question/explicit memory form; numeric clock punctuation remains data for the
independent temporal guard.
For why/change/memory, --entity now narrows identity AND preserves every query
term. It cannot erase an unrecognized qualifier or another entity name.
Generic Why? --entity ID and matching names remain positive controls; dependency
identity resolution is unchanged. Public README and bilingual CLI help state
the distinction. Installed bilingual assertions cover relative periods, colon
clauses, mismatching identity-bound terms, and exact generic-identity sources.
All original authority/source/byte-invariance assertions remain. All30findings,
latest-head review, complete hosted gates and fresh main remain mandatory.
No local AFTER while Work is unavailable; no HUMAN or complete PM015/Alpha claim.


Findings4090002819/4090002822/4090002828 bring the tracked total to33.
BEFOREd114cd5ad129dc0eb32bea59ff3d0ac7bc43bd84 /35956835863 /
Ubuntu3.11 job107497034669: 800tests,17failures,52skips,101.083s.
The original BEFORE and prior797-test installed AFTER are retained.
Remember is recognized as an imperative after a conjunction. This is reconciled
with finding22: bare memory/mémoire remains a noun in a conjunctive entity name,
and punctuation introduces the explicit Memory shorthand. Adding every bare
memory noun as a conjunction-level intent would reintroduce the proven
risk-and-memory-management refusal. Public grammar and old/new tests preserve
both cases; mixed requests using Remember or punctuation abstain.
Car is no longer globally rejected as a target-name token; actual embedded
question/dependency markers remain guarded. Explicit RFC/ISO/IEC/IEEE number
prefixes are masked only for the temporal scan, retaining every lexical query
term and distinguishing the recorded standard identities.
Real installed bilingual queries cover the new names/commands with exact source
opening and all prior byte/authority assertions. All33findings, distinct latest
review, complete hosted gates and fresh main remain mandatory. Work unavailable;
no local AFTER, HUMAN or full semantic PM015/Alpha claim.


Finding4090063735 is tracked as34. BEFORE0e46ae564941874d9bbe014139d31bfd94e50c5d /
35957770710 / Ubuntu3.11 job107499894695:801tests,9failures,52skips,95.665s.
The complete original log is retained. The guard now abstains on a Remember
command later in a conjunctive clause regardless of its prefix, rather than
enumerating only please/do spellings. After explicit punctuation it also guards
prefixed Memory/Mémoire shorthand. Two additional noun-shorthand controls are
not attributed to that prior BEFORE. Immediate recognized compounds keep their
existing mixed/multiple reasons; otherwise the reason is
unsupported-compound-memory-clause. Bare memory nouns after conjunctions and
explicit literal --kind memory remain available with exact source assertions.
The actual installed bilingual journey covers these cases and byte invariance.
The33b1afa provider max558.800441>500ms failure remains unresolved; full evidence
is on9f4a684ebb5764e66286d83aeb00a1d5acc57972. This functional correction does not
fix or erase that PM012/merge hold. New CI verifies concrete changed behavior.
All34findings, final review and all gates/fresh main remain mandatory. No local
AFTER while Work is unavailable; no HUMAN or Alpha claim.


Latest distinct review5300041703 raises findings4090127468/4090127475/
4090127481/4090127489 (38total): non-ISO hyphen dates, abbreviated month dates,
named-zone clocks and adjacent period-separated question clauses.
BEFORE48c332459c9ec146df7d2059cd90c65f897eac8d /35958895056 /
Ubuntu3.11 job107503318258:805tests,36failures,52skips,95.363s.
The full original BEFORE and preceding801-test Linux AFTER are retained.
Unsupported hyphenated dates, EN/FR abbreviated/full month-number forms, named
zone/offset clocks now abstain. Embedded identifier boundaries and all earlier
date/CLI-bound checks remain. Adjacent periods split only before a supported
question form with following argument whitespace, preserving System.Memory,
foo.memory.py and dotted software versions. Prefixed memory commands after
nonnumeric periods also abstain; decimal version punctuation is preserved.
The installed bilingual journey repeats the new date/zone/compound cases
against old matching paths or all-term fixture labels and opens exact sources
for the dotted-name positives. No prior authority, byte, source or direction
assertion is removed. All38findings, latest-head review and complete gates remain
required. The33b1afa provider max558.800441>500ms incident is still unresolved;
these question changes do not fix it or establish Alpha/HUMAN readiness.


Review5300151500 on c960ee6 adds findings4090220923/4090220930/4090220934
(41total). BEFORE0c2f510c7ad2c2d10e036e0c720fe550bf5ed6a4 /35960335738 /
Ubuntu3.11 job107507412610:808tests,49failures,52skips,97.652s.
The original log is retained. Adjacent French elided forms now recognize the
whole interrogative prefix, rather than requiring whitespace after qu'.
Abbreviated month-first dates accept ordinal suffixes for the ambiguity guard;
standalone year-first dates with variable-width month/day fields also abstain.
Identity selection and explicit CLI bounds do not bypass these constraints.
All earlier positive names, dotted versions and ISO-bound/source/byte/authority
assertions remain. Installed bilingual cases cover all three new families.
The preceding c960ee6 run ended20PASS/4cancelled as real new regressions arrived;
its805-test and installed Ubuntu PASS do not qualify this new head. Full logs
are retained. All41findings and latest-head review/required gates remain open.
The provider558.800441>500ms incident remains unresolved; no main merge,
local AFTER, complete PM015, HUMAN or Alpha is claimed.


Finding4090301777 is tracked as42. BEFORE2a01805ab0dde1d54699266f96f62b03c136797a /
35961005325 / Ubuntu3.11 job107509667542:809 tests,12 failures,52 skips,106.582s.
The full BEFORE and preceding808-test/installed Ubuntu AFTER logs are retained.
Standalone three-component dotted dates with a four-digit year now abstain,
independently of identity selection and CLI bounds. Two-component versions and
three-component software versions without a four-digit year remain data;
embedded dotted release/build identifiers retain their boundary protection.
Both new positive identities and date negatives run through the installed
bilingual CLI with the original exact sources and byte/authority checks.
All42 findings, latest-head review and full gates remain required. This does
not resolve the preserved provider558.800441>500ms incident or PM012100k.
No local AFTER, merge, full semantic PM015, HUMAN or Alpha claim.
