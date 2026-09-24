Finding-by-finding verification on candidate **877b2b06ba60bbc5e07e273f42b74434d3a0046b** (MACHINE, not HUMAN).

Each review finding's concrete failure scenario was replayed in its own disposable repository against the installed wheel of this candidate (Windows, Python 3.12.10): expected abstention/citation, every citation opened by id and hash, journal bytes unchanged, `assurance: none`, no action, question not stored. To show that each scenario detects its defect, the same scenario was run on an earlier build: the first reviewed commit 36341f8, the commit where the finding was reported (when the defect was introduced later), 7af22d6 for 59 and 09bf096 for 60–61. Replay script SHA-256 `3fca09241c67f0a93d9c9931fb8ae3c51fe40f5857678b450bbbcc4a518a0d3f`; scenarios 1–59 are unchanged since the earlier-build runs (only the 60–61 scenarios and a selection argument were added); logs are kept with the local evidence.

Result: **61/61 PASS** on the candidate; every scenario FAILS on the listed earlier build. Threads 1–59 are resolved individually on this basis; 60–61 stay open until the independent review of this head.

| # | Comment | Candidate 877b2b0 | Earlier build |
|---|---|---|---|
| 1 | 4088785920 | PASS — dependency-direction-ambiguous; dependency-direction-ambiguous | 36341f8 FAIL |
| 2 | 4088785929 | PASS — ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 3 | 4088833583 | PASS — dependency-direction-ambiguous | f144d2b FAIL |
| 4 | 4088833589 | PASS — ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 5 | 4088878860 | PASS — mixed-question-intents; mixed-question-intents | 36341f8 FAIL |
| 6 | 4088878864 | PASS — ambiguous-time-filter; ambiguous-time-filter; ambiguous-time-filter; a | 36341f8 FAIL |
| 7 | 4088878867 | PASS — exit 2, no traceback | 36341f8 FAIL |
| 8 | 4088930520 | PASS — ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 9 | 4088979861 | PASS — ambiguous-time-filter; ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 10 | 4088979869 | PASS — cited SRC-AUTH | 36341f8 FAIL |
| 11 | 4089040597 | PASS — cited SRC-A,SRC-B | 36341f8 FAIL |
| 12 | 4089081719 | PASS — insufficient-cited-records | 80d3ef7 FAIL |
| 13 | 4089181415 | PASS — ambiguous-time-filter | 36341f8 FAIL |
| 14 | 4089288605 | PASS — insufficient-cited-records | ef0b937 FAIL |
| 15 | 4089288609 | PASS — ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 16 | 4089335578 | PASS — dependency-direction-ambiguous | 36341f8 FAIL |
| 17 | 4089335580 | PASS — ambiguous-time-filter; ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 18 | 4089390630 | PASS — ambiguous-time-filter | 36341f8 FAIL |
| 19 | 4089471249 | PASS — ambiguous-time-filter; ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 20 | 4089587924 | PASS — cited CM; cited CM | 998acd4 FAIL |
| 21 | 4089587933 | PASS — cited ISO | 998acd4 FAIL |
| 22 | 4089734559 | PASS — cited RISK | fd24c18 FAIL |
| 23 | 4089734563 | PASS — cited PY | fd24c18 FAIL |
| 24 | 4089734565 | PASS — cited REL | fd24c18 FAIL |
| 25 | 4089850123 | PASS — ambiguous-time-filter | 36341f8 FAIL |
| 26 | 4089850128 | PASS — cited SRC; cited SRC | c1a6948 FAIL |
| 27 | 4089873151 | PASS — multiple-question-clauses; multiple-question-clauses | 36341f8 FAIL |
| 28 | 4089873155 | PASS — exit 2 for empty --since/--until | 36341f8 FAIL |
| 29 | 4089948783 | PASS — ambiguous-time-filter; ambiguous-time-filter; ambiguous-time-filter | 36341f8 FAIL |
| 30 | 4089948792 | PASS — multiple-question-clauses; mixed-question-intents | 36341f8 FAIL |
| 31 | 4090002819 | PASS — mixed-question-intents | 36341f8 FAIL |
| 32 | 4090002822 | PASS — cited SRC | 6d35bc2 FAIL |
| 33 | 4090002828 | PASS — cited RFC | 6d35bc2 FAIL |
| 34 | 4090063735 | PASS — unsupported-compound-memory-clause | 36341f8 FAIL |
| 35 | 4090127468 | PASS — 12 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 36 | 4090127475 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 37 | 4090127481 | PASS — 12 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 38 | 4090127489 | PASS — multiple-question-clauses | 36341f8 FAIL |
| 39 | 4090220923 | PASS — mixed-question-intents | 36341f8 FAIL |
| 40 | 4090220930 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 41 | 4090220934 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 42 | 4090301777 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 43 | 4090360930 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 44 | 4090360937 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 45 | 4090360945 | PASS — mixed-question-intents; mixed-question-intents | 36341f8 FAIL |
| 46 | 4090442851 | PASS — cited PLAN; cited TYPO | 855a850 FAIL |
| 47 | 4090514176 | PASS — 12 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 48 | 4091207915 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 49 | 4091207921 | PASS — cited PLAN | d861ec8 FAIL |
| 50 | 4091207928 | PASS — cited SRC | d861ec8 FAIL |
| 51 | 4091207932 | PASS — mixed-question-intents | 36341f8 FAIL |
| 52 | 4091385402 | PASS — mixed-question-intents | 36341f8 FAIL |
| 53 | 4091385410 | PASS — cited SRC; cited SRC | 289ea90 FAIL |
| 54 | 4091527848 | PASS — 12 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 55 | 4091691319 | PASS — 18 abstentions ambiguous-time-filter; cited SDK | 36341f8 FAIL |
| 56 | 4091691327 | PASS — mixed-question-intents | 36341f8 FAIL |
| 57 | 4092623217 | PASS — mixed-question-intents | 36341f8 FAIL |
| 58 | 4092727135 | PASS — 6 abstentions ambiguous-time-filter | 36341f8 FAIL |
| 59 | 4092842170 | PASS — 6 abstentions ambiguous-time-filter | 7af22d6 FAIL |
| 60 | 4093864173 | PASS — 12 abstentions ambiguous-time-filter | 09bf096 FAIL |
| 61 | 4093864180 | PASS — cited REL0; cited REL1 | 09bf096 FAIL |
