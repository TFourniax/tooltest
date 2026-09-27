# PM012: 100k history acceptance and separate profiling

The product source is main c03164e75e805ff1df976e55cdf6d86073e89b04.
Diagnostic candidate b7ca3ce184a726986447284da8bb929b2268d53c adds only workflow
and diagnostic script. Actual hosted checkout is synthetic merge
4382bd9652255beae3c0b4846a64351b0642d3ca. Python3.14.7/Linux.
Run35943160391/job107455301898 preserves the original failure.

Unprofiled existing workload:100000events,batch2000,7hotcontexts:
append10.900786s FAIL10s; fullverify4.949088s FAIL2s; rebuild10.307589s FAIL5s.
Contextcold63.015ms and hotp9562.638ms PASS existing1000/300ms.
The existing10k gate and retrieval corpus PASS. No budgets were changed.

Separate cProfile diagnostic completed both profiled calls and immutable-journal
assertions and wrote both pstats. Its final metadata print then raised TypeError
because st_size was incorrectly called. This diagnostic step FAILED, so it must
not be described as a completely successful run. The next commit corrects that
attribute access. The complete original log is preserved.

The profile is diagnostic, not a performance acceptance result:
verification10.450s profiled; _validate_event_shape6.219s cumulative,
_event_integrity3.349s, JSON parsing2.124s.
Rebuild18.725s profiled; validated reread10.486s, projection7.065s,
SQLite executemany5.767s including generator time, entity terms2.167s.
Cumulative figures overlap; they must not be added or treated as unprofiled
timings. They identify work to inspect, not a proven optimization or system cause.

No product optimization is included yet. The failing100k gate deliberately
blocks qualification. Previous local100k and cross-platform hook incidents
remain open. No local execution after Work went offline is claimed. Latest-head
review, all gates and freshmain are required before any technical merge.
MACHINE global incomplete; HUMAN not executed; not Alpha Ready.
