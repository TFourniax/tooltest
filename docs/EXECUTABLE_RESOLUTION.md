# Installation-bound hook executables — issue #54

## Finding and invariant

Windows human qualification found explicit installation A generating hooks for installation B because B came first on PATH. Reproduced independently with two installed wheels in separate Linux/Python 3.12 virtual environments, before implementation. Reordering PATH alone switched both generated Codex Protect commands. Classification: P1.

Baseline: qualified HT-009 candidate `d5cbd2b488d6189da5cd2276f9509973f68c2e61`, merged in `7f50981abe1a58f2c09604f88c387269c756ec52`. The old FAIL and HT-009 HUMAN PASS remain in issue #52. This is a separate correction.

**Invariant:** hooks installed by DiffWitness target the intended running installation unless the user explicitly selects another executable using `DIFFWITNESS_BIN`. PATH must not silently choose another installation. Persisted hook ownership remains authoritative for inspecting/removing previously installed hooks.

## Resolution decision

1. An explicit `DIFFWITNESS_BIN` is an executable selection, not a shell command. Resolve a named executable once through PATH, or an explicit path relative to the current invocation. Validate it before changing hooks and store an absolute path.
2. In PyInstaller, use the frozen `sys.executable` bootloader path. Never use the temporary `_MEIPASS` extraction directory or the build machine's Python launcher.
3. For a recognized, explicitly located `dw` console launcher, use its existing executable. Windows distlib launchers may remove `.exe` from `sys.argv[0]`; recover the adjacent `.exe`. Resolve pipx/POSIX symlinks to their installed target. A bare argv name is not enough to select a file in the project's working directory.
4. For Python module/programmatic entry, locate the `dw` console script in the running DiffWitness distribution's installed file record, validating that the distribution corresponds to the loaded package (including editable installs). Do not guess from Python's executable: it is the interpreter, not `dw`, and its Scripts directory can differ for user installs.
5. If none is available, fail with an actionable request to install the intended package or set an explicit executable. Do not guess another `dw` from PATH.

Native setup must also select its bundled `idleproof` entry from that same distribution, unless `--idleproof-command` / `DIFFWITNESS_IDLEPROOF_BIN` deliberately selects a compatible external integration. A standalone binary without a paired sidecar needs that explicit external sidecar selection for setup; Protect itself targets the running binary. Adding a new standalone sidecar distribution is outside this fix.

Selection is not code signing or an assertion that a path can never be replaced. An intentional upgrade at the same installation path remains supported. This resolver does not edit Codex trust, approve hooks, alter provider payload syntax, change Proof authority or widen Portal data.

## Packaging evidence used for the decision

- [PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html): frozen executable versus Python interpreter, symlinks and extraction paths.
- [Python installed distribution metadata](https://docs.python.org/3/library/importlib.metadata.html): distribution file records and file locations.
- Installed pip/distlib console script template inspected locally: normalization can strip `.exe` from argv[0].

## Qualification matrix

Require actual installed-artifact checks for two venvs, both PATH orders, explicit command, module entry, user Scripts, pipx, explicit override, reinstall/upgrade, and standalone binary. Windows/macOS/Linux CI executes the applicable matrix. Unit fixtures cover missing launchers, stripped Windows suffixes, symlinks, metadata mismatch, explicit override validation, and failure before hook mutation.

Consumer checks must invoke generated hooks and prove they reach the intended installation. A mocked PATH test alone is insufficient. Targeted Windows/Codex human qualification is still required before merge; frozen HT-009 unknown-trust/observed semantics and all native/Protect regression gates must remain green.
