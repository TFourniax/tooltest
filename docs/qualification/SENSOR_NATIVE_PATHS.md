# Native path coverage in the advisory redundancy sensor

Registry #74; audit B/F-02/AD-11 (C3). Baseline
`4501e91275a07492447c1276e940b0fb936e230e`.

Git display-quoted names were split as lines and filtered as source filenames.
The sensor now uses the shared Git byte reader with NUL framing. Native identities
remain unchanged; undecodable UTF-8 names are explicitly counted as unsupported.
Coverage reports file limits and unreadable sources instead of silently implying
the entire candidate was scanned. No threshold, signal points or authority changes.

Real-Git tests cover accents, spaces, quotePath true/false and, where representable,
POSIX tabs/newlines/literal backslashes. A raw non-UTF8 Git object test runs without
depending on the host filesystem's filename rules. A sufficiently large semantic
reimplementation is detected in project and change scans with exact path provenance;
an unrelated function is excluded. Existing exact-copy exclusion remains tested.

Initial baseline: 4 failing subcases and one missing-coverage error in three tests.
Final installed wheel: 4 regression tests PASS. Debt suites: 46 tests PASS.
Full installed suite: 723 tests, 52 explicit skips, zero failures.
Wheel SHA-256: `e64c168643171cb5bf638a15bf887c6e79aec6662c5260f949e4921d5927254a`.
Raw logs are preserved losslessly beside this document.

MACHINE only. Last-head independent review, hosted OS matrix and fresh main remain
required. This bounded correction does not complete PM-012/018 or qualify Alpha.

## Final-review correction

Review 4087810620 found that changed-line selection still parsed display headers.
The added real-Git regression fails in 12 subcases on 60fc133. A single
NUL-framed raw+patch Git stream now binds each zero-context patch to its native
path; external diff/text conversion and rename display heuristics are disabled.
Exact changed lines, unrelated additions, seven POSIX names and quotePath variants
are exercised. Invalid framing fails explicitly rather than guessing an identity.
The original findings/logs remain. Updated installed wheel: all 724 tests PASS,
52 explicit platform/dependency skips, 71.387 seconds. Wheel SHA-256: `82c765b21a2eb0e76e3a1133627f4b05731222a4d3c6c9a15b3344eab2e7b8d9`. Review and remote qualification of the new commit remain required.
