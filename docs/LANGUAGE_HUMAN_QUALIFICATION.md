# LANG-001 / HT-003: targeted Windows human qualification

Run only after reviewing the exact machine-green candidate recorded in the PR. Use that exact installed candidate and verify its provenance with `pipx runpip diffwitness freeze` (or the equivalent installer provenance). No merge/tag is authorized by this procedure. Do not reuse or modify the preserved HT013/HT014 failed fixture.

Use a fresh disposable repository on French Windows. Keep the original OS/shell locale; optionally set `$env:LANG='fr_FR.UTF-8'`, `$env:LC_ALL='fr_FR.UTF-8'`, `$env:LANGUAGE='fr_FR:fr'` for this shell. Select the installed executable explicitly, e.g. `$dwLang = 'C:\Users\33672\.local\bin\dw.exe'`.

1. Create a new folder and `git init`. Run `& $dwLang`, `& $dwLang status`, `& $dwLang doctor`, `& $dwLang setup status`. The default human presentation must be English. No language preference should have been saved automatically. On this empty project, doctor/setup may correctly report that verification is not ready; record their exit codes rather than treating that as a language failure.
2. Run `& $dwLang setup --agent codex`. This is the one deliberate setup operation. Save SHA-256 of `.codex/hooks.json` and `.git/HEAD`, plus `.git/index` if present. Record `& $dwLang protect status --json`. No provider task or Protect enable/disable cycle is requested.
3. Capture `status --json`, `doctor --json` and `setup status --json` through `& $dwLang --language en ...`, then through `& $dwLang --language fr ...`. Compare parsed JSON and corresponding exit codes: identical facts and outcomes. JSON reason codes/enums and evidence are canonical.
4. Run `& $dwLang --language fr status`, `doctor`, `setup status`, and `setup --help`. Human presentation should be French. Commands, symbols, user content and quoted canonical diagnostics/evidence are preserved verbatim.
5. Run `& $dwLang language fr`, then `& $dwLang status` to check persistence. `& $dwLang --language en status` must be English for that invocation; the next ordinary `status` must still be French. Changing language must not change the saved Guided/Technical view.
6. Compare `status --view guided` and `status --view technical` under each explicit language. Both must expose the same readiness/unknown/unborn/Proof/protection facts. Do the same with doctor. No language change may turn unobserved into observed or unknown into verified.
7. Run `& $dwLang language en`. Ordinary status/doctor/setup must return to English. Recheck the saved hook/HEAD/index hashes, Protect JSON and absence of `.claude`: unchanged by the language operations. Only the explicit language/view preferences may change.

Return the exact candidate SHA, installer provenance, Windows/Codex version if installed, command outputs/exit codes, JSON comparisons and file hashes. This qualifies language presentation only; it does not claim any new provider runtime or application test execution. No unrelated provider-real Protect replay is needed.
