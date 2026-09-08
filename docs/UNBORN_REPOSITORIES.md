# HT013 / HT014 — repositories before their first commit

Reproduced before implementation on qualified main `4a53a9fd9f338b7deaa11ade26d02c933c86b6bf`: setup fails while fingerprinting HEAD; setup status then loses useful diagnostics; status raises a traceback; native SessionStart cannot capture a baseline. Both empty and already-staged initial repositories reproduce it. Captured outputs: `qualification/ht013-ht014-before.json` (temporary paths normalized).

## Decision before implementation

An unborn branch is a supported state, not a broken repository. Detect it only when HEAD is a valid symbolic local-branch reference with no corresponding ref. A corrupt or invalid detached HEAD must still fail; never treat corruption as an empty project.

Analytical operations can resolve an unborn HEAD to a deterministic unreachable empty commit/tree. No branch, HEAD, user index, working file or user Git identity is changed. Ordinary reference resolution and commit-attestation operations remain strict: the analytical base is not a real first user commit. Existing committed repositories keep their previous base semantics.

Snapshots use the existing alternate index, with its existing tracked/untracked/exclusion rules, against the empty analytical base. This supports native SessionStart before any first commit, initial worktree files and a first task's actual Proof/Debt/Continuity boundary. No change and no previous evidence remain explicit; empty/clean is not VERIFIED.

Before a root commit exists, no clone-stable lineage exists. Use a durable randomly scoped **local provisional** identity under common Git metadata, with exclusive first-writer creation and no silent repair/reset on corruption. Independent empty repositories must differ; moving the same repository must not reset its provisional identity. Concurrent first callers must agree. After the first real user commit, the established root-lineage fingerprint rule applies. Old envelopes/events remain historical with their original identity and are never silently rebound to the new lineage. Re-ingesting an old provisional envelope as current lineage must fail closed. Existing local exact-tree coverage remains governed by the existing tree reader.

JSON/readiness and Guided/Technical output explicitly name the unborn state, empty analysis base and local identity scope. Portal network synchronization requires a first real commit; it must not publish a provisional identity as stable lineage. The Portal schema and actual remote ingestion path are not redesigned in this phase.

After the first commit, a Portal snapshot must also reject historical evidence whose repository identity differs from the current root lineage. A new captured task can supply new evidence; local historical envelopes are never deleted or silently relabeled. Read-only Git status calls disable optional index refresh so initial staging bytes remain intact throughout the native journey.

## Qualification requirements

Empty and staged repositories; initial code files; no existing user identity; corrupt HEAD versus unborn; deterministic empty base; exact user index/HEAD/ref/file preservation; two repositories and concurrent identity initialization; first native task and Proof freshness; first user commit transition; strict ordinary ref resolution; no provider trust or hook syntax changes. Run the full existing OS/Python, ProofBench, ContinuityBench, integrated product and package/binary consumer gates.

This changes the behavior of native task capture before the first commit. A minimal real Windows/Codex first-task qualification is required before merging, even though the established committed-repository provider contracts remain unchanged. No broad replay of already-qualified committed-repository cases and no Alpha tag/release.

## Targeted Windows/Codex human qualification

Use the exact candidate SHA recorded in the PR's machine qualification comment. Install that SHA into the existing pipx installation, verify provenance with `pipx runpip diffwitness freeze`, and invoke its absolute `dw.exe`. Keep the qualified installation-bound hook rule; do not use an unverified PATH command. Record the Codex version. No need to repeat committed-repository Protect scenarios.

In PowerShell, create a new disposable folder and keep this shell open:

```powershell
$dwUnborn = Join-Path $env:USERPROFILE '.local\bin\dw.exe'
$repoUnborn = Join-Path $env:USERPROFILE ('dw-unborn-human-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory $repoUnborn | Out-Null
Set-Location $repoUnborn
git init -q
git config core.autocrlf false
$utf8Unborn = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $repoUnborn 'app.py'), "def add(a, b):`n    return a - b`n", $utf8Unborn)
New-Item -ItemType Directory tests | Out-Null
[IO.File]::WriteAllText((Join-Path $repoUnborn 'tests\test_app.py'), "import unittest`nfrom app import add`nclass T(unittest.TestCase):`n    def test_add(self): self.assertEqual(add(2, 3), 5)`n", $utf8Unborn)
[IO.File]::WriteAllText((Join-Path $repoUnborn '.diffwitness.toml'), "[diffwitness]`ntest = 'python -m unittest discover -s tests -q'`nstability_runs = 1`nmax_total_seconds = 120`n", $utf8Unborn)
git add app.py
$indexUnborn = (Get-FileHash .git\index -Algorithm SHA256).Hash
& $dwUnborn setup install --agent codex --json
& $dwUnborn status --json
& $dwUnborn status --view guided
& $dwUnborn status --view technical
$hooksUnborn = (Get-FileHash .codex\hooks.json -Algorithm SHA256).Hash
codex --version
codex
```

Before Codex: setup succeeds, JSON is parseable, repository state is `unborn`, `hasHead=false`, `identityScope=local-provisional`; installation alone does not imply observation or Proof. If Codex requests hook trust, make the decision through Codex's own `/hooks` flow. Relaunch a fresh session if necessary for SessionStart.

Give Codex only this task:

> Fix `add` in `app.py` so the existing test passes. Change only `return a - b` to `return a + b`. Do not change tests/configuration, stage files or create a commit. Run the existing tests. Let the native DiffWitness Stop hook finish; do not run dw guard or dw gate.

After the real task completes, exit Codex and run:

```powershell
& $dwUnborn setup status --json
& $dwUnborn status --json
& $dwUnborn doctor --json
& $dwUnborn state status
"INDEX IDENTICAL=" + ($indexUnborn -eq (Get-FileHash .git\index -Algorithm SHA256).Hash)
"HOOKS IDENTICAL=" + ($hooksUnborn -eq (Get-FileHash .codex\hooks.json -Algorithm SHA256).Hash)
git rev-parse --verify HEAD
# Expected: HEAD does not exist (exit 128); the hook must not create a user commit.
git --no-optional-locks status --short
Test-Path .claude
```

Required: native observation is true while Codex `providerTrust` remains `unknown`; native Stop reports accepted Proof and non-degraded Continuity; current tree is verified; repository remains unborn; index and hook hashes match; no Claude configuration; only the intended app change. Preserve complete outputs and exact installed candidate provenance.

Then explicitly create the fixture's first **user** commit (Git user identity may need the user's normal configuration):

```powershell
$envelopeUnborn = (Get-FileHash .git\diffwitness\change-envelope.json -Algorithm SHA256).Hash
git add app.py tests/test_app.py .diffwitness.toml
git commit -m 'first user commit after unborn qualification'
& $dwUnborn status --json
& $dwUnborn portal status --json
"ENVELOPE IDENTICAL=" + ($envelopeUnborn -eq (Get-FileHash .git\diffwitness\change-envelope.json -Algorithm SHA256).Hash)
"HOOKS IDENTICAL=" + ($hooksUnborn -eq (Get-FileHash .codex\hooks.json -Algorithm SHA256).Hash)
```

Required: repository becomes `committed` with root-lineage identity; exact-tree Proof stays applicable; historical envelope and hook bytes remain identical. Portal synchronization of that old provisional envelope is intentionally refused until new task evidence exists under the current identity. This is a local qualification; no Portal credential or remote upload is needed.
