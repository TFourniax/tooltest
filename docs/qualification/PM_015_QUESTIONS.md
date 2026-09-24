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


Review5300314258 adds findings4090360930/4090360937/4090360945 (45 total).
BEFOREbcb85dade69e651f3845a4d63f8794309fe7b3db /35961897418 /
Ubuntu3.11 job107512382114:812 tests,54 failures,52 skips,143.856s.
Extended/compact ISO weekday dates and generic ET/CT/MT/PT clock qualifiers
now abstain. Em/en dashes and spaced ASCII dash separators recognize a following
supported question form; prefixed memory commands use the same dash boundaries.
Existing name, numeric, source, byte and authority controls remain unchanged.
The installed bilingual journey adds old-path and all-term-label regressions.

The e7506d1 installed Ubuntu job107510913752 failed an exact-ID assertion.
Its newly added release-21.09.2026 fixture shares the complete lexical term set
of the existing release-2026-09-21 fixture. The baseline bcb85da changes only
that new fixture to dotted-21.09.2026 and adds context to the unchanged assertion.
The actual bcb85da installed Ubuntu107512382213 then PASSES without a product
change. Original labels and exact-ID/source assertions remain. Full failed and
successful logs are retained. A further unit test and actual installed cases
explicitly verify both sources for equal lexical term sets and exact --entity
selection; these additional positive controls were not in the 812-test BEFORE.
They document lexical lookup, not full-phrase identity resolution or semantic Q&A.
All45 findings, latest-head review and full gates remain mandatory. The earlier
provider558.800441>500ms incident and PM012100k remain unresolved. No local AFTER,
merge, full PM015, HUMAN or Alpha claim.


Finding4090442851 is tracked as46. BEFORE75add4e2ad8fd0d78370cecc9128d43d89ed6a60 /
35962880322 / Ubuntu3.11 job107515376349:814 tests,8 failures,52 skips,82.255s.
Generic ET/CT/MT/PT zones now use a scoped case-sensitive alternative inside
the existing case-insensitive temporal scan. The uppercase clock negatives
remain unchanged; French lowercase et and lower/mixed-case pt name terms
retain their exact source identities. All four positive names also execute
through the bilingual installed CLI with the existing source/byte assertions.
The preceding855a850 run ended13PASS/11cancelled when this concrete regression
was pushed, not a full matrix PASS. Its813-test/installed Linux results and
this original BEFORE are retained. Latest-head review and full gates remain
required. Provider incident, full PM015/PM001-018 and HUMAN/Alpha remain open.


## Batched correction, Work restored, 2026-09-24

Review finding 47 (4090514176): standalone dotted dates with two-digit years
now abstain under the same temporal boundary as the existing four-digit forms.
The corpus covers day/month and month/day forms, leading zeros, CLI bounds and
entity narrowing. Two-component versions, Node 24.1.0, explicitly attached
identifiers (`v24.1.10`, `release-21.09.26`) and four-component versions remain
literal names. Ambiguous bare date-shaped tokens still abstain; no source or
bound is fabricated.

Per the user's current instruction, code and coverage were grouped locally,
then tested; no regression-only commit or per-case CI run was created.
70 Q&A tests pass. The complete installed-wheel suite passes 814 tests with
52 explicit skips. The installed CLI acceptance passes, opens original sources,
and preserves journal/state bytes; journal SHA-256
`d24c053b7069d52b743f85b2f31926d97344a15267429799ead6ff38cd3b0a84`.
An initial source invocation used a relative PYTHONPATH that did not survive
fixture cwd changes; its subprocess import failure was fixed in the environment,
without changing an assertion. No HUMAN execution is claimed.

The provider latency incident remains OPEN under PM012. The Q&A diff against
main adds a lazy `ask` dispatch, its reader and acceptance workflow step; it does
not modify extraction, providers or their budgets. A final review and fresh
full candidate CI are still required. No global MACHINE/Alpha claim follows.


Grouped latest-head review corrections48–51 (2026-09-24): standalone EN/FR
abbreviated month tokens abstain as ambiguous time, including explicit CLI bounds
or an entity constraint. Attached names such as sept-sdk remain lexical names.
Uppercase conventional time-zone codes remain time constraints; lowercase/title
case French est/cet and existing et/pt name homographs remain literal terms.
Incoming dependency grammar admits Doctor Who, what/which platform and French
relative-pronoun names without treating every interrogative token as a new clause.
Actual direction/compound clauses still abstain. Ampersand-separated question
intents are inspected before answering, including NFKC full-width ampersands;
ampersands inside names followed by ordinary nouns remain literal.

The grouped product patch passes72 focused tests and816 installed-package tests
(52 explicit skips,90.053s). Wheel389172bytes:
450734fda5bbf17cfa98f3b15acd769b038d79ab9d5df0a3503816a68bf9a82e.
The expanded installed CLI acceptance initially found a fixture collision:
'risk & memory retention' and 'risk and memory retention' share all significant
lexical terms, so expecting one result without --entity was incorrect. The new
ampersand fixture now uses 'risk & memory conservation'; exact-ID/source and
abstention assertions remain unchanged. Only that failed acceptance journey was
rerun; product code and the already passing816-test suite did not change.
Final installed CLI journey passes with every source opened and journal/state
bytes preserved. No additional CI was pushed per individual finding.

Prior d861ec8 has test35971656258 all24jobs PASS plus three specialists PASS;
that result does not qualify this new patch. Latest-head distinct review, fresh
hosted gates and post-merge main remain required. PM015 and PM001–018 remain
partial/open; provider latency incidents and PM012100k failures remain open.


Grouped findings52–53: slash/pipe separators before recognized questions no
longer disappear into lexical terms; prefixed memory commands are checked at
those boundaries too. Incoming dependency targets may contain internal !/?/;
punctuation and ordinary slash/pipe names; recognized second clauses still
abstain. Positive cases include Yahoo! service, status? probe, alpha; boundary,
comma-separated names and paths/what gateway. EN/FR and exact entity selection
remain covered.72 focused tests and816 installed-wheel tests PASS (52skips,
87.471s). Actual installed CLI journey PASS after fixing an overlapping fixture
name; original failure preserved and all fixture label term sets checked for
containment. Only the failed journey was rerun, without product-code changes.
Wheel389171bytes SHA25614677cd60dcf39b6605370bf2ab6c1e88440ac5c497e5410b48b143b29d3f5fd.
Sources opened; journal SHA6046d641f112bf5c47eb4d1d4978f1aeac2897aa8904696b02116444a55506b7
unchanged. No HUMAN or full semantic PM015 completion is claimed.


Review54/4091527848: standalone ordinal dates YYYY-DDD and YYYYDDD now abstain,
including compact/extended clocks, fractional seconds and zone offsets. The
reader never turns those date constraints into path tokens. Attached release,
version, directory and underscore identities remain positive exact-source cases.
73 focused tests PASS;817 installed-wheel tests PASS(52skips);actual installed
CLI acceptance PASS,sources opened and original journal/state bytes preserved.
Wheel389209bytes SHA2563fdb739888125cede060f7ad008efd2ebbe43a17f8751556115fa1863002659b.
Journal07438ceec4335443436557435033b0c2889e4421912896efe915620f2889e3f0 unchanged.

To bound review cost,67 original qualification files(11764237bytes) are retained
byte-for-byte at verified branch evidence/pr128-through-9add906,commit9add906.
PM_015_QUESTIONS/evidence-index.json records every original path,size,SHA256,blob
and immutable URL. Only their duplicate inclusion in the product diff is removed;
no test,budget or original evidence is dropped. The product diff loses85275lines
of historical logs while full evidence remains independently reachable. New batch
logs use the existing evidence/work-batch-20260924 branch. Final-head CI/review
remain mandatory; the local wheel qualified above contains unchanged product
source across this evidence-only relocation.


The same numeric-date guard now covers compact calendar dates and attached clocks
on calendar/week forms as a single family, preventing another unsupported date
from becoming an unbounded path query. Prefixed version/release/build identities
remain literal.73 focused tests and817 installed-wheel tests PASS (52skips,
93.106s),actual installed CLI acceptance PASS. Wheel389225bytes:
9ecab60dbda72758f77bad7badb3f55c296bcca0b3b40bd8f835d1b21e1cc81d.
Journal/state remain unchanged; original sources are opened. Final candidate
review and hosted gates are still required; no result transfers between SHAs.

## Work continuation — grouped findings 55–56, 2026-09-24

Review comments 4091691319 and 4091691327 on b83719b are addressed together.
Named-month dates accept numeric hyphen/slash/dot separators for detection,
including French abbreviations, ordinal days and NFKC forms. Parentheses,
brackets and braces before recognized questions or prefixed memory commands
retain compound intent. Ordinary attached identifiers and parenthesized names
remain positive exact-citation cases.

The two expanded regressions against b83719b reproduce 78 failing subcases.
The installed corrected wheel passes 74 focused tests and the full suite:
818 tests, 52 explicit skips, 98.792 seconds. The initial full invocation from
the parent directory failed one test-module import (`scripts` absent from
sys.path); its log is retained. Running the documented command from the repo
root fixes the harness invocation without modifying an assertion or product.
The real installed CLI journey also passes with original citations opened and
journal/state bytes unchanged. Local wheel SHA256:
fcfa0498a495149d2582f141e4315fae8cf471e825d737fb94b2f9bd7ec82fbd.

Latest-head independent review, hosted gates and fresh main remain required.
This is bounded extractive Q&A, not full semantic PM015 or HUMAN acceptance.
PM012 provider and 100k incidents remain separate release blockers.

## Work continuation — finding 57, 2026-09-24

Review 4092623217 on 5cc6ed9 exposed conversational prefixes hiding a second
supported question inside a separated clause. Intent detection now scans those
clauses for recognized interrogatives after arbitrary prefix words, rather than
enumerating polite phrases. It deduplicates matches by their original position;
ordinary names and unsupported interrogative-like tokens remain covered.

The regression against 5cc6ed9 reproduces 352 failing subcases across eight
prefixes, eleven boundaries and four supported EN/FR question tails. The fixed
candidate passes 75 focused tests and 819 installed-wheel tests, with 52 explicit
skips, in 93.235 seconds. The actual installed CLI journey passes, opens original
citations and preserves journal/state bytes. Local wheel SHA256:
ea4559ce8f35db35b2f799d818d062aec82e0f56b5d255123057e22c2db82539.
Journal SHA256: 5348376fb373fe401330f7f253cdb08b2b7f7fbe08f3c777a73ec6835c464596.

These are MACHINE results. Independent review and hosted gates must bind this
new commit before merge; fresh main must then be checked. Full PM015, PM012 and
all other uncompleted PM requirements remain outside this closing slice.

## Work continuation — finding 58, 2026-09-24

Review 4092727135 on 42d80ea exposed standalone two-component hyphen dates
without a year. The existing hyphen-date family now includes optional years,
spacing around separators and attached compact/extended clocks. NFKC forms and
EN/FR questions are covered; attached release, path, version and underscore
identifiers remain positive exact-source cases. Explicit CLI bounds and identity
selection cannot erase an ambiguous question-side date.

The expanded regression reproduces 60 failing subcases on the installed 42d80ea
product. After correction, 75 focused tests PASS, 819 installed-wheel tests PASS
(52 explicit skips, 92.076 seconds), and the real installed CLI journey PASS.
The new journey names were checked for overlap with existing fixtures and made
distinct without changing assertions. Original sources are opened and journal/
state bytes remain unchanged. Wheel SHA256:
9823b0920e31aa88bef123961aa7bc78dfb4c53c1ff7a808d79b0f7afa7830a6.
Journal SHA256: 5cfdbe935028a7b2d272258bf6fd1c65ed015754148af62c2da8591f647721c0.
This local wheel precedes this documentation update; it is not a published
release. Fresh exact-head review/CI and post-merge main remain required.

## IDE continuation — finding 59, 2026-09-24

Review 4092842170 on 7af22d6 exposed spaced two-component slash dates such as
`09 / 21`. The numeric date separator family is now corrected together: slash
dates accept separator spacing, attached compact/extended clocks and the
U+2215/U+2044 slash forms that NFKC keeps distinct; hyphen dates and named-month
dates accept the U+2010–U+2014 dash and U+2212 minus forms; three-component
dotted dates accept separator spacing and attached clocks. Two-component dotted
versions and attached release, path, underscore and version identifiers remain
positive exact-source cases. Lookbehind guards are unchanged, so no previously
abstaining question becomes answerable.

The regression against the installed 7af22d6 wheel reproduces 78 failing
subcases (13 forms, EN/FR, three option sets). After correction on Windows with
Python 3.12.10: 76 focused tests PASS; 820 installed-wheel tests PASS with 49
explicit skips (absent optional grammars and the POSIX pipx contract) in 1020.172
seconds; the real installed CLI journey PASS, opens original citations and
preserves journal/state bytes. A first journey attempt failed because two new
fixture names produced identical query terms; it was a fixture overlap, kept in
the local log, and one name was made distinct without changing assertions.
Local wheel SHA256:
bda2ceaafacca96aa87d66799c9ac3c9aba8cc2380b783d0fefe9511c9d87b22.
Journal SHA256: 430990e17dd6c82137305acbdb079f09b3fc17eb0ef76b4d6401829ad3787124.
These are MACHINE results. Independent review and hosted gates must bind the new
commit before merge; fresh main must then be checked.

## IDE continuation — findings 60–61, 2026-09-24

Review 5304738054 on 09bf096 reported two findings, corrected together.

Finding 60 (4093864173): two-component named-month dates with an attached
compact or extended clock (`Sep-21T120000Z`, `21-SepT120000Z`, slash/dot
forms) bypassed the guard because the terminal boundary cannot precede `T`.
All named-month alternatives now consume the same attached clock as the numeric
date branches.

Finding 61 (4093864180): 09bf096 named Unicode dash/slash variants inside the
date branches while the attachment guards stayed ASCII, so `release‐09‐21`
(U+2010) became unqueryable although `release-09-21` is protected; the cited
`release‐2026‐09‐21` already abstained on 7af22d6 through the standalone-year
branch. The branch-level variant classes are replaced by one mapping: before the
clause and temporal scans, U+2010, U+2011, U+2012 and U+2212 are read as `-`, and
U+2215 and U+2044 as `/`. Attachment, separation and clause boundaries therefore
follow the ASCII rules exactly, and query terms are unchanged. En and em dashes
remain punctuation that separates date components and clauses, not identifier
attachments. Consequently, identifiers attached with these hyphen/minus/slash
variants become answerable like their ASCII spellings, while dates written with
them still abstain. Only an ASCII ISO date can form the supported `since`
bound; its Unicode spelling abstains.

The regression against the installed 09bf096 wheel reproduces 41 failing
subcases: 30 named-month clock cases, 6 Unicode-attached identifiers and 5
Unicode clause separators whose result now must equal the ASCII form.
After correction on Windows with Python 3.12.10: 76 focused tests PASS; 820
installed-wheel tests PASS with 49 explicit skips (absent optional grammars and
the POSIX pipx contract) in 1153.730 seconds; the real installed CLI journey
PASS, opens original citations and preserves journal/state bytes. Local wheel
SHA256: 6d827ad54a7399265f9497e707b1e8b675fb8ca2bef02a06e79d324d3d37a906.
Journal SHA256: 854db8b33c0b3f87b7aff1a5a8a81182322974cd3cfe8cba4ed35782ec164a20.

The concrete scenario of every review finding 1–61 was also replayed in its own
disposable repository against the installed product, opening each citation and
checking journal bytes: 61/61 PASS on this candidate. Each scenario is shown to
detect its defect: 58/59 on 7af22d6 (59 fails), 14/59 on the first reviewed
commit 36341f8, every one of the other 14 fails on the commit where it was
reported, and 60–61 fail on 09bf096. These are MACHINE results; independent
review and hosted gates must bind this commit, then fresh main must be checked.

## IDE continuation — finding 62, 2026-09-24

Review 5305158962 on 877b2b0 (4094207977, P1): the case-sensitive named-zone
list omitted common abbreviations such as `EET`, `EEST`, `WET` and `WEST`, so
`What changed in auth 12 EET?` could cite an older `auth/12/eet/` path. The list
is now one module constant of 192 customary tz-database abbreviations, a strict
superset of the previous 31, still matched case-sensitively after a one- or
two-digit hour. Lowercase or capitalized words (`est`, `cet`, `wet`, `West`,
`eet`) and non-zone uppercase terms such as `IT` remain exact-source names.

The regression against the installed 877b2b0 wheel reproduces 90 failing
subcases (15 zone forms, EN/FR, no bound / `--until` / `--entity`).

Hosted gate note for 877b2b0: in run 36006223408, job 107654947849 (installed
optional syntax providers, ubuntu-latest, attempt 1) FAILED on the unchanged
IdleProof hook latency budget: `tree-sitter-json` p95 152.8 ms > 150 ms
(max 204.7 ms < 500 ms). Its first 24 samples were 72–76 ms before
second-half spikes; `python-ast` and `tree-sitter-typescript` measured 52.0 and
73.8 ms p95, below 7af22d6 (69.8/96.5 ms) and 09bf096 (71.7/96.2 ms), whose
JSON p95 were 98.3 and 106.6 ms. The gate runs extraction hooks; the Q&A
module is imported only by `dw ask`. This failure is retained as a FAIL of that
commit; no budget was changed and it does not qualify or disqualify another SHA.

After correction on Windows with Python 3.12.10: 76 focused tests PASS; 820
installed-wheel tests PASS with 49 explicit skips in 1093.095 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
c0f3b3f24eb564e7e26891dfb4155b06e54f62d48f1af2b40cd7b4c970326c02.
Journal SHA256: 9baac7107620e0de480a8cf12339cfbf694626df123d730132e764043fdd5b61.
The replay of every review scenario gives 62/62 PASS on this candidate; the
finding-62 scenario fails on 877b2b0. MACHINE results only; independent review
and hosted gates must bind this commit before merge, then fresh main.

## IDE continuation — finding 63, 2026-09-24

Review 5305677379 on 4e256a6 (4094642025, P2): the customary zone constant
still omitted tz-database abbreviations such as `AHST`, `AHDT`, `HKST`, `YST`
and `YDT`. The constant now contains every alphabetic abbreviation stored in
the 598 TZif files of IANA tz database 2026d (Python `tzdata` 2026.4, 115
abbreviations, extracted from the binary files rather than typed by hand)
plus the previous customary forms: 250 in total, still case-sensitive. A
hermetic regression pins those 115 abbreviations. tz numeric abbreviations
such as `+03` or `-01` are covered by accepting a two-digit offset after a clock.

The same family was audited for attached forms and corrected together: a clock
(`H`, `HHMM`, `HH:MM[:SS]`, `HH.MM`, `HHh[MM]`, with am/pm, or noon/midi/
midnight/minuit) followed with or without a space by a zone (`12:00EST`,
`1200EST`, `3pmEST`, `12hEET`, `noonEST`, `12.30 EET`), a numeric offset
(`1200+03`), Zulu `Z` (`1200Z`, `0930Z`, `T1200Z`, `120000Z`) or an attached
hour unit (`1200hrs`, `12 hrs`). Attached identifiers keep the existing
lookbehind guard (`v1200Z`, `build_1200EST`, `rev12hEET`) and remain
exact-source positives, as do dotted versions without a zone.

Regressions against the installed 4e256a6 wheel reproduce 124 failing
subcases for the tz-database set (58 abbreviations, `+00`, `+03`, attached
`12AHDT`) and 102 for the attached forms (17 forms, EN/FR, three option sets).

After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1014.414 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
b2aba5ba439087caad6c878a12a2038369be29c156bf219b6f8a989a28e5b428.
Journal SHA256: ef8a9d3214e800318afb48d0bfe7030810ded6dd8f3af2f2fa58961c90e9eaf2.
The replay of every review scenario gives 63/63 PASS on this candidate; the
finding-63 scenario fails on 4e256a6. 4e256a6 itself passed its 27 hosted
checks (test 36011104805, ProofBench 36011104389, ContinuityBench 36011104454,
integrated 36011104258), which do not qualify this new commit. An earlier local
run of an intermediate state of this lot was stopped before the attached forms
were added; its partial logs are kept and are not counted.

## IDE continuation — finding 64, 2026-09-24

Review 5306130604 on 716910a (4095024653, P2): an uppercase Zulu `Z` after an
`h`-style clock (`12h30Z`) matched neither the clock/zone branch nor the numeric
Zulu branch. The accepted clock shapes (H, HHMM, HH:MM[:SS], HH.MM, HHh[MM],
optional am/pm, noon/midi/midnight/minuit) are now defined once and shared by
the zone, offset, Zulu and IANA-zone-name suffixes, so `12h30Z`, `12hZ`,
`3pmZ`, `noonZ`, `midnightZ` and `12.30 Europe/Paris` abstain as well. The
generalized Zulu suffix is case-sensitive so a lowercase unit such as `60hz`
stays a name; the existing numeric Zulu branch keeps its case-insensitive
behaviour. No fractional part is accepted before a generalized suffix, so a
version such as `1.2+34` stays a name. The regression against the installed
716910a wheel reproduces 36 failing subcases (6 forms, EN/FR, three option sets).

After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1018.110 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
9a9172c65e579603b58a4cae371a090b79e55d32cadca817fc1d000bbef12ba4.
Journal SHA256: eb10609e50822453cb686bde6a238c8882487da5bf89d8fd8f7a6de754ce9169.
The replay of every review scenario gives 64/64 PASS on this candidate; the
finding-64 scenario fails on 716910a. 716910a passed its 27 hosted checks
(test 36015591600, ProofBench 36015591620, ContinuityBench 36015591536,
integrated 36015591543), which do not qualify this new commit.

## IDE continuation — finding 65, 2026-09-24

Review 5306494614 on eacd74f (4095330252, P2): the shared clock suffix ended at
a word boundary, so an attached identifier such as `12h30Z-service` abstained
although 716910a treated it as data. A suffix separated by a space still
qualifies the clock unchanged (`12 EST`, `12 EST/PST`, `12 EST-service`, `12 +03`).
A suffix attached without a space now takes the date patterns' right guard,
so hyphen-, slash- or plus-suffixed tokens (`12h30Z-service`, `1200EST-api`,
`3pmZ-build`, `1200Z-service`, `12h30Z/api`, `12h30Z+plugin`) are names. The same
guard applies to the numeric Zulu and attached hour-unit branches introduced in
this lot (`1200hrs-report`). A zone may carry a POSIX offset (`12EST-5`,
`12 EST+5`), which still abstains.

One deliberate relaxation follows the uniform rule: the attached form
`12EST-service` abstained on 7af22d6 through the former zone branch and is
now an exact-source name like the other attached identifiers. Spaced forms and
every attached clock followed by punctuation or the end of the question still
abstain. The regression against the installed eacd74f wheel reproduces 8
failing subcases (the eight attached identifiers).

After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1137.370 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
f597173069d5c9261f87d2dd3e1177aeb752cd8f17228c639fd581c8ec0a5b57.
Journal SHA256: 361928ce899cc1582f6a6a94b56379fc0866a79c760bee5cc4a803d98dc3ac3d.
The replay of every review scenario gives 65/65 PASS on this candidate; the
finding-65 scenario fails on eacd74f. eacd74f passed its 27 hosted checks
(test 36019272770, ProofBench 36019272714, ContinuityBench 36019273046,
integrated 36019272746), which do not qualify this new commit.

## IDE continuation — finding 66, 2026-09-24

Review 5306843914 on 5c3d529 (4095630671, P2): the hour-unit branch combined
optional spacing with the attached-identifier guard, so the spaced qualifier in
`12 hrs-service` no longer abstained. It is now split like the clock suffix:
a unit after a space (`12 hrs-service`, `12 hr-report`) qualifies the clock and
abstains, while an attached unit (`12hrs-service`, `1200hrs-report`) keeps the
right guard and stays a name. The regression against the installed 5c3d529
wheel reproduces 12 failing subcases (2 forms, EN/FR, three option sets).
After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1099.778 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
27ef107e5f976a3698643ad02c4fdf71d147dfc0e15d9ca8c09005b266afa2b6.
Journal SHA256: 9e280e63bf4fd2f27206299014b29c60d5892d6284412466180ad03df62d53dd.
The replay of every review scenario gives 66/66 PASS on this candidate; the
finding-66 scenario fails on 5c3d529. 5c3d529 passed its 27 hosted checks
(test 36023359779, ProofBench 36023359655, ContinuityBench 36023359831,
integrated 36023359856), which do not qualify this new commit.

## IDE continuation — findings 67–68, 2026-09-24

Review 5307199747 on 935b183 reported two findings, corrected together.

Finding 67 (4095927154, P2): zone names in POSIX form (`EST5EDT`, `CST6CDT`,
`MST7MDT`, `PST8PDT`) after an hour were lexical terms. A zone suffix now
accepts the POSIX shape `STD[offset][DST[offset]]` (`EST5EDT`, `CET-1CEST`,
`EST-5`, `EST-0500`, `EST5`, `UTC0`, with or without a trailing rule such as
`,M3.2.0,M11.1.0`). Minutes of an unsigned offset require a colon, so sensor or
product names such as `12 PT100 probe` and `12 PT1000 probe` stay names; a
first local draft without that rule made `PT100` abstain, was caught by a
neighbouring-form probe before any push, and its interrupted run logs are kept.

Finding 68 (4095927165, P2): the bare clock branch evaluated `Z` under the
outer case-insensitive flag, so `12z compression` abstained. Zulu `Z` is now
case-sensitive in that branch and in the numeric Zulu branch added in this lot
(which also made `1200z router` abstain, a regression of this lot relative to
7af22d6). Lowercase `z` after a number is a unit or name; `UTC`/`GMT` remain
case-insensitive. This is a deliberate, documented relaxation for `12z`, which
abstained on 7af22d6.

The regression against the installed 935b183 wheel reproduces 50 failing
subcases (8 POSIX forms, EN/FR, three option sets, and the two `z` names).
After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1088.409 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
c8f284b41dea6d5771c6b6e5184255582dc6d133b5ea831add8cf837010c61bb.
Journal SHA256: 0bf26689d89e31f48816d0bf79bee04fdd958e3434fdb42a9cc717ca7e4537b8.
The replay of every review scenario gives 68/68 PASS on this candidate; the
finding-67 and finding-68 scenarios fail on 935b183. 935b183 passed its 27
hosted checks (test 36026705588, ProofBench 36026705564, ContinuityBench
36026705707, integrated 36026705593), which do not qualify this new commit.

## IDE continuation — finding 69, 2026-09-24

Review 5307672012 on bd787f6 (4096333942, P2): legacy IANA zone IDs outside
the continent allowlist (`US/Eastern`, `Canada/Pacific`, `SystemV/...`) after an
hour were lexical terms. The zone-ID branch now lists every namespace directory
of the IANA tz database 2026d package (Africa, America, Antarctica, Arctic, Asia,
Atlantic, Australia, Brazil, Canada, Chile, Etc, Europe, Indian, Mexico,
Pacific, US; 553 namespaced IDs, at most two levels) plus the historic SystemV,
and accepts digits in components (`SystemV/EST5EDT`, `Etc/GMT+5`). Single-word
legacy IDs such as `Japan`, `Turkey` or `GB` are ordinary words (`12 GB volume`)
and are not treated as zones; those that are also abbreviations or POSIX zones
(`CET`, `GMT0`, `EST5EDT`) already abstain. Without an hour, `US/Eastern region`
stays a name. The regression against the installed bd787f6 wheel reproduces 24
failing subcases (4 forms, EN/FR, three option sets).
After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1088.524 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
08673f4bfc3162f2dbec403b730917b9223c808ebaf2d66454b88f849e4e7c6e.
Journal SHA256: 67282ef4d3b1588c51bf0c653e2b9dfe11e7289a1b99e29e5c96c6b02b7b132f.
The replay of every review scenario gives 69/69 PASS on this candidate; the
finding-69 scenario fails on bd787f6. bd787f6 passed its 27 hosted checks
(test 36031471753, ProofBench 36031471603, ContinuityBench 36031471369,
integrated 36031471539), which do not qualify this new commit.

## IDE continuation — finding 70, 2026-09-24

Review 5308011423 on 460f540 (4096627454, P2): top-level tz links with a hyphen
(`NZ-CHAT`, `W-SU`) after an hour were lexical terms; the finding-69 correction
had left all single-component IDs out. The clock suffix now accepts, exactly
and case-sensitively, every top-level zone ID of the IANA tz database 2026d
(43 IDs: `Japan`, `Turkey`, `Zulu`, `UCT`, `NZ-CHAT`, `W-SU`, `GB-Eire`, `GMT+0`,
...) except `GB`, a common unit after a number (`12 GB volume` stays a name), and
the `Factory` placeholder, which is not a real zone. Lowercase or inflected words
remain names (`12 japan tea`, `12 Japanese restaurants`), as does a zone ID
without an hour (`Japan office`).

Hosted gate note for 460f540: in run 36035271297, job 107753665806 (installed
optional syntax providers, ubuntu-latest, attempt 1) FAILED on the unchanged
IdleProof hook latency budget: `python-ast` p95 202.2 ms > 150 ms (max 380.8 ms
< 500 ms). The median sample was about 53 ms, as on earlier heads, with isolated
spikes of 125–381 ms; this path does not import the Q&A module. The failure is
retained for that commit; no budget was changed. The regression against the
installed 460f540 wheel reproduces 42 failing subcases (7 forms, EN/FR, three
option sets).
After correction on Windows with Python 3.12.10: 78 focused tests PASS; 822
installed-wheel tests PASS with 49 explicit skips in 1060.947 seconds; the real
installed CLI journey PASS with citations opened and journal/state bytes
unchanged. Local wheel SHA256:
968f23a0bf56794439de6313d3fc15c5a5dd6b102934d103f8340d9a943bbf6c.
Journal SHA256: e1a19a7fe0a03b8374cdc49d08b4d6b9904779b5584ee81716560b29d88c2dd1.
The replay of every review scenario gives 70/70 PASS on this candidate; the
finding-70 scenario fails on 460f540. 460f540's other hosted results were
SUCCESS (ProofBench 36035271162, ContinuityBench 36035271189, integrated
36035271004); none of them qualifies this new commit.
