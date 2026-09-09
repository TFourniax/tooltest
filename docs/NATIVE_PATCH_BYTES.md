# HT013/HT014: native counterfactual patch byte preservation

## Human finding and pre-fix reproduction

Candidate `2e0b4a0a0e0d1f7fd1f50be79bc0e011654da123` is MACHINE PASS / WINDOWS-CODEX HUMAN FAIL. The owner's full evidence is preserved in PR #57 comment 5589439579; the master issue record is #52 comment 5589439744. The Windows fixture `C:\Users\33672\dw-unborn-human-20260908-191513` must remain untouched. Do not commit/reset/restage/reinstall into or rewrite that fixture.

The reproduction uses a valid unborn repository, `core.autocrlf=false`, original `app.py` staged, unchanged tests/configuration untracked, and only the working-tree return expression changed. It runs `session_start`, `user_prompt_submit`, and `session_stop`, including the real Proof analysis and detached worktrees. It does not substitute a Gate helper or fabricate evidence results.

The failure is `analysis.run_analysis` reversing the single hunk in the disposable candidate worktree:

```
git apply --whitespace=nowarn -R -
exit 1
error: patch failed: app.py:1
error: app.py: patch does not apply
```

The later forward sufficiency application in the base worktree fails for the same byte mismatch. Both evidence executions already establish BASE STABLE-FAIL / CANDIDATE STABLE-PASS. The task baseline is the captured initial files, not the empty analytical commit; candidate and baseline snapshots preserve their file bytes. The user's real index is not used to apply counterfactual hunks. Changing Python availability, user staging, hook trust or the empty base cannot repair the failed patch context.

Pre-fix diagnostic capture is in `qualification/ht013-ht014-apply-error-before.json`. It includes empty analytical base, task/candidate commit and tree IDs, generated hunk, forward/reverse direction, disposable worktree HEAD/index, application input/file hex, exit/stderr and native Stop result. Random temporary paths/ephemeral IDs are diagnostic values, not user fixture identities.

| File bytes | Git text-pipe behavior | Native result before fix |
| --- | --- | --- |
| LF | Actual Linux | Accepted Proof and Continuity |
| CRLF | Actual Linux | Stable fail/pass contrast, then apply-error |
| LF | Windows stdin translation isolated on Linux | Same contrast and apply-error |
| CRLF | Windows stdin translation isolated on Linux | Accepted Proof and Continuity |

The emulated rows are explicitly not real Windows qualification. A separate tests-only commit `e23d72aa331515e6389e0c3a8846f24bfaa5c0dd` runs explicit LF/CRLF native regressions and installed consumer fixtures on actual Windows before the product change.

Actual Windows confirmation before coding: workflow `34259758025`, installed wheel job `102174471949`, reproduces the same stable fail/pass then `INCONCLUSIVE [apply-error]` in `codex LF first task`, using absolute Python 3.12.10. Task baseline `33cedd264dc572edde1731408e3501898645d557`; candidate `6f19d13bd77626accd9d258d20ef2d447c7c6fbb`. PR #57 comment 5589512149 records that confirmation. This separates the failure from evidence-command discovery experimentally, not just by inference.

Windows Python 3.12 native regression job `102174471851` additionally captures actual LF file hex, hunk/context, direction, baseline/candidate trees, sandbox HEAD and Git stderr. The extracted diagnostic and its source artifact provenance are preserved in `qualification/ht013-ht014-apply-error-windows.json`. All four Windows Python versions reproduce the failure before the fix; these failing runs are intentional historical reproduction evidence, not replacement qualification.

## Root cause and machine coverage gap

`gitops.diff_text` read a Git patch through `subprocess` text stdout, converting CRLF to LF. `gitops.apply_patch` then sent it through text stdin, converting LF to the host line separator. Python documents both conversions: [subprocess text-mode streams](https://docs.python.org/3.12/library/subprocess.html#frequently-used-arguments).

The old installed acceptance script used `Path.write_text` without `newline`, creating LF files on Linux and CRLF files on Windows. Its fixtures therefore matched the host's patch conversion. The human PowerShell fixture used UTF-8 without BOM with explicit LF. On Windows, valid LF patch context became CRLF on stdin and could not match the LF candidate file. Git's `core.autocrlf=false` does not disable Python pipe conversion. The native Linux CRLF failure independently demonstrates the reciprocal lossy stdout boundary.

## Intended smallest correction

Use existing binary subprocess plumbing for Git patch output/input only. Decode UTF-8 with surrogateescape for the existing string parser and re-encode reversibly at application; never normalize line endings or replace source bytes. Apply the same rule to candidate reduction diffs. Keep `--whitespace=nowarn` and `-R` behavior; add no whitespace/context relaxation. Do not modify the generic command runner, user files/index/HEAD, provider hooks/trust/executable resolution, Proof acceptance or inconclusive behavior.

Regressions must exercise explicit LF and CRLF bytes on every OS, assert the actual native base/candidate contrast, witnessed hunk and accepted persisted Proof, current-tree binding, Continuity and Debt, and preserve index/hooks/HEAD/config/test bytes. Exact installed Windows wheel and standalone journeys must use the same explicit byte fixtures. An unrelated/non-applicable patch must still fail closed. Existing committed-repository and benchmark gates remain required because patch transport is shared.

After a replacement SHA is fully machine-qualified, owner review precedes the same targeted Windows/Codex human journey in a fresh disposable fixture. Keep the failed fixture untouched. Do not merge or tag before targeted HUMAN PASS and subsequent exact-main qualification.
