# PR128 exact-head evidence, 2026-09-24

Candidate 33b1afa0eba886806bc35547ff15a7ab250550da; source tree7cf6fc9990d9c11ced5f49f78a3bf09b4873f721.
Run35957187387. Actual checkout46522ac6fe30aae5c2a54ee3e85d116d544ad410
has the API-verified same tree, parentsc03164e75e805ff1df976e55cdf6d86073e89b04
and33b1afa0eba886806bc35547ff15a7ab250550da. The checkout SHA is distinct from the reviewed head.

Ubuntu3.11 job107498222868:800tests PASS,52skips,101.104s.
Installed optional syntax providers Ubuntu job107498223040: FAIL.
Python-ast Node22.23.2/Linux/x64/4CPUs: p95=79.963834ms <=150ms;
max=558.800441ms >500ms. Original samples and all log lines retained.
The consumer checkout is2b919f7dddeaf3488091017a46f079d8c9718056.
The canonical feature smoke passed; the shell stopped at the Python latency
failure, so subsequent TypeScript/data perf commands are not claimed executed.
No root cause is inferred from timing alone. No budget, assertion or timeout
is changed, and no retry-to-green is requested.

This evidence branch preserves logs without moving PR128's tested/reviewed head.
It is not a qualified product candidate, not a merge request, and not a release.
Remaining matrix jobs/review are recorded in PR128 and canonical issue74.
Known100k/provider issues and PM001–018 development remain open.
No HUMAN, Alpha, deployment, publication or local AFTER claim.
