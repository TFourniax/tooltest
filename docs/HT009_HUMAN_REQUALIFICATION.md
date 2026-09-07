# HT-009 — Windows Codex requalification

Status: **PENDING HUMAN**, merge-blocking for the readiness candidate. This is not the final Alpha qualification.

Baseline evidence: issue #52, CP-01 through CP-05, core `e9bf514a3f13b1fc4124e3ff6a0e416016a2790b`, Codex 0.153.2. Use the exact head SHA of the HT-009 PR after all machine/packaging gates pass; record it with the output. Never use a moving branch as the recorded candidate.

## Install and record

Use the existing disposable Windows Codex-only qualification project and its usual Python environment. Record:

```powershell
Get-Date -Format o
[System.Environment]::OSVersion.VersionString
Get-Command python, dw, codex
codex --version
dw --version
```

Install the exact candidate into the Python environment that owns the displayed `dw` executable:

```powershell
python -m pip install --force-reinstall "git+https://github.com/TFourniax/tooltest.git@<EXACT_CANDIDATE_SHA>"
python -m pip show diffwitness
```

Do not run `dw setup` again in the previously qualified project for the re-enable scenario: it intentionally resets native observation and would change the precondition being tested. If provider hooks still point to an older executable environment, correct the installation selection before proceeding.

## A — Establish normal native/Protect operation

1. Record `dw setup status --json`, `dw protect status --json`, and `.codex/hooks.json`.
2. Enable Protect if off: `dw protect enable --policy standard`.
3. Open Codex normally. Follow its own `/hooks` review only if requested. Never bypass trust.
4. Ask: `Run exactly git status --short once. Do not edit any file or run another command.`
5. Exit Codex and confirm Protect has `activeSeen=true`, `activation=observed`, `ready=true`, and receipts `integrity=true`. Native hooks must still be installed/observed.

## B — The HT-009 regression

```powershell
$hooksBefore = Get-Content .codex/hooks.json -Raw
dw protect disable
dw setup status --json
Get-Content .codex/hooks.json
dw protect enable --policy standard
($hooksBefore -eq (Get-Content .codex/hooks.json -Raw))
dw protect status --json
dw view guided
dw protect status
dw setup status
dw doctor
dw view technical
dw protect status
dw setup status
dw doctor
```

Expected:

- Disable removes only PreToolUse/PostToolUse; SessionStart/UserPromptSubmit/Stop remain.
- Re-enable restores the same hooks (comparison should be true); no Claude project integration appears.
- Before another real tool call: Protect `installed=true`, `activeSeen=false`, `ready=false`, `activation=awaiting-first-observation`, `providerTrust=unknown`, `observedAt=null`.
- Native observation remains present; no existing native hook trust is lost.
- Human output explains missing observation and conditional Codex review. It must not state that approval is still necessary when Codex retained it.
- Existing French/English mixing is still HT-003, not a completed localization fix.

Reopen Codex and repeat the single harmless command from A. Record what Codex actually shows in `/hooks`. Previously approved identical hooks should remain approved; report any unexpected review. After invocation, Protect must return to observed/ready with an intact receipt chain and a nonempty `observedAt`. `providerTrust=unknown` remains deliberate: DiffWitness does not read Codex's trust store.

## C — Coexistence confirmation

Repeat the already-qualified CP-05 task in the disposable fixture with a fresh, bounded failing test and a single production fix. Let Codex finish normally, without manual Gate or `dw guard`. Require strict native JSON acceptance, accepted Proof bound to the exact current tree, matching change/certificate IDs, coherent Debt/Continuity, and all five hooks still present. Do not use a no-change task as substitute evidence of new Proof production.

## Evidence and severity

Return exact candidate/core SHA, OS, provider version, commands/prompts, stdout/stderr, `/hooks` observations, before/after hook files, setup/Protect/status JSON, and CP-05 certificate/change IDs. Redact secrets; no raw private source or transcript is needed.

- P0: provider trust bypass, destructive action executes despite expected block, or runtime observation becomes Proof.
- P1: trust/observation lie, missing native hooks, strict JSON rejection, failed native Proof coexistence, lost persisted approval for identical hooks, invalid receipts.
- P2/polish: wording density/layout that preserves the facts; pre-existing HT-003 remains separately release-blocking.

Any P0/P1 prevents merge. Preserve previous qualification evidence and append the result to issue #52. The later Alpha phases in the execution audit remain required after this boundary.
