# CLI informational and syntax boundary

Registry: Core #74. Source alias: audit A/AUD-01 (C1).
Baseline: `4501e91275a07492447c1276e940b0fb936e230e`.

The public gate wrapper could remove a historical certificate before parsing,
and the frontend could execute test-only evidence before interpreting help or
invalid syntax. The repair parses with the existing command grammar before
either boundary. Direct frontend and proof CLI callers share that protection.
The gate parser is extracted, without changing its options or proof policy.
An informational token inside a test-command value remains a test argument.

The regression uses real disposable Git repositories, harmless external markers,
and inventories every file (including Git objects and historical certificates).
It covers outside/clean/dirty/tests-only/unborn repositories, short/long help,
version, absent config with help, malformed options and explicit evidence.
No provider trust, certificate hash, evidence discovery, or execution budget is weakened.

Machine evidence in `CLI_INFORMATIONAL_SAFETY/`:

- Final five-test regression against the unchanged baseline: 36 failing subcases.
- The same regression against the installed wheel: PASS.
- Full installed suite runs from the repository root, where its `scripts` package
  is importable. See the final raw log for count, skips and result.
- Candidate wheel SHA-256: `8948a27a867e70b8db3ccaf102b26af0ef6365ec2fd65ceddbc955bb3b872ebf`.

Earlier attempts are retained in the private mission evidence with hashes in
`attempts.json`: the first oracle wrongly expected the word "usage" in Guided
root help; a baseline attempt overlapped an edit and was repeated in a detached
unchanged worktree; initial full runs lacked installed entrypoints or the root
`scripts` import path. They are not product failures or passing qualification.
An initial source installation into a bare venv failed because its build backend
was absent; the available build runtime built the wheel subsequently installed.

PR review, hosted OS/binary gates and fresh post-merge main remain required.
No HUMAN, coordinated Alpha, publication or deployment claim.

The follow-up qualification adds the same regression through the actual installed
`dw` console script and built standalone binary on all three hosted OS families.
The new test-only executable override does not affect runtime behavior. The local
console-script run passes all five tests. Earlier candidate runs remain evidence;
the last commit must be reviewed and tested again.
