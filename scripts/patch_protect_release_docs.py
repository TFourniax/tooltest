from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one replacement anchor, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    replace_once(
        "README.md",
        """```bash
dw protect enable
```

Keep an existing external harness:
""",
        """```bash
dw protect enable
```

For current Codex builds, installing the hook file is only the first step: Codex itself must have its `hooks` feature enabled, the repository must pass Codex's normal project-trust flow, and the DiffWitness hooks must be approved through Codex's own hook-trust UI. DiffWitness never grants itself that trust. `dw protect status` stays conservative until a live Codex hook has actually invoked Protect. See [`docs/PROTECT.md`](docs/PROTECT.md).

Keep an existing external harness:
""",
    )
    replace_once(
        "README.md",
        """Builtin Protect currently supports Claude Code and Codex hook surfaces. It starts with a bounded deterministic rule set for high-confidence cases such as destructive Git/filesystem operations, remote pipe-to-shell execution, writes outside the repository, direct `.git` writes, several credential/private-key patterns, destructive database/schema commands, dependency-install observation/confirmation, and lightweight post-edit JSON/Python syntax checks.
""",
        """Builtin Protect currently supports Claude Code and Codex hook surfaces. Current Codex hooks are provider-feature/trust gated: DiffWitness can install its hook configuration, but it never enables project trust or approves its own hooks. Until a live trusted Codex hook reaches DiffWitness, the Codex adapter is reported conservatively rather than pretending runtime protection is active.

Protect starts with a bounded deterministic rule set for high-confidence cases such as destructive Git/filesystem operations, remote pipe-to-shell execution, writes outside the repository, direct `.git` writes, several credential/private-key patterns, destructive database/schema commands, dependency-install observation/confirmation, and lightweight post-edit JSON/Python syntax checks.
""",
    )
    replace_once(
        "README.md",
        """- `strict` additionally asks for confirmation on dependency installation.
""",
        """- `strict` additionally asks for confirmation on dependency installation where the provider hook protocol supports it; current Codex `PreToolUse` does not safely support `ask`, so Protect blocks that dependency-install action instead.
""",
    )
    replace_once(
        "README.md",
        """Protect receipts intentionally exclude raw commands, source contents, raw prompts, raw agent-event streams and raw session identifiers. Portal receives only aggregate mode/health/policy and decision counts when sync is configured.
""",
        """Protect receipts intentionally exclude raw commands, source contents, raw prompts, raw agent-event streams and raw session identifiers. A provider's first live hook may add one bounded `active` receipt so readiness can mean "the hook actually ran" without inventing a risk finding. Portal receives only aggregate mode/health/policy and decision counts when sync is configured.
""",
    )

    replace_once(
        "docs/PROTECT.md",
        """- Claude Code;
- Codex.

### External
""",
        """- Claude Code;
- Codex.

#### Codex activation and trust

Current Codex builds keep lifecycle hooks behind Codex-owned feature and trust boundaries. `dw protect enable` installs DiffWitness's project hook configuration, but DiffWitness deliberately does **not** grant itself Codex trust.

For Codex builtin Protect, complete Codex's own flow:

1. enable Codex's `hooks` feature (for example, `codex --enable hooks`, or the equivalent user-owned Codex configuration);
2. accept Codex's normal project-trust decision for the repository;
3. review and approve the DiffWitness hooks in Codex's `/hooks` surface;
4. let Codex invoke a tool, then check `dw protect status`.

Until a live trusted Codex hook actually invokes DiffWitness, the Codex adapter remains conservatively not-ready rather than claiming protection that has not run. DiffWitness never writes Codex project trust, never writes a trusted hook hash on the user's behalf, and never uses Codex's dangerous hook-trust bypass in product code.

### External
""",
    )
    replace_once(
        "docs/PROTECT.md",
        """High-confidence dangerous actions are blocked and dependency-install requests ask for confirmation.
""",
        """High-confidence dangerous actions are blocked. Dependency-install requests ask for confirmation when the provider hook protocol safely supports that decision. Current Codex `PreToolUse` rejects `ask`, so strict Protect blocks that dependency-install action instead of silently downgrading the policy.
""",
    )
    replace_once(
        "docs/PROTECT.md",
        """Session identifiers are represented only by a short digest.

Check aggregate state:
""",
        """Session identifiers are represented only by a short digest.

The first live invocation from a configured provider may add one bounded activation receipt (`decision=active`, `category=runtime`). That is a transport/readiness marker, **not** a risky-action finding and not a proof claim. Subsequent safe calls do not need to create repeated activation receipts.

Check aggregate state:
""",
    )
    replace_once(
        "docs/PROTECT.md",
        """For a repository already using its own harness:
""",
        """For Codex builtin Protect, after enabling Protect complete Codex's provider-owned hook/trust flow before expecting runtime interception:

```bash
dw protect enable --policy standard
codex --enable hooks
# In Codex: accept the repository trust prompt, then review/approve DiffWitness in /hooks.
dw protect status
```

For a repository already using its own harness:
""",
    )

    replace_once(
        "docs/60_SECONDS.md",
        """```bash
dw protect enable
```

Delegate live protection to an existing harness:
""",
        """```bash
dw protect enable
```

With current Codex builds, also enable Codex's own `hooks` feature and complete Codex's normal repository + hook trust flow. DiffWitness installs its hooks but never approves itself. After a live Codex tool call, `dw protect status` confirms whether the adapter has actually been observed. See [`PROTECT.md`](PROTECT.md).

Delegate live protection to an existing harness:
""",
    )

    replace_once(
        "src/diffwitness/public_help.py",
        """Protect policy is independent from Guard proof policy. Clean actions are never force-allowed by
DiffWitness; provider-native permissions remain authoritative. `off` installs no Protect interception.
""",
        """Protect policy is independent from Guard proof policy. Clean actions are never force-allowed by
DiffWitness; provider-native permissions remain authoritative. `off` installs no Protect interception.
Current Codex hooks are provider-feature/trust gated: DiffWitness installs configuration but never writes
Codex project/hook trust. Complete Codex's own trust flow (including `/hooks`) and use `dw protect status`
to confirm that a live hook has actually reached Protect.
""",
    )
    replace_once(
        "src/diffwitness/public_help.py",
        """Runtime protection is optional:
  dw protect use external            Keep your existing harness and let DiffWitness verify the result
  dw protect disable                 Use no DiffWitness live interception; Proof and Debt still work

A blocked or observed runtime action is not proof that the final software works. DiffWitness verifies the
""",
        """Runtime protection is optional:
  dw protect use external            Keep your existing harness and let DiffWitness verify the result
  dw protect disable                 Use no DiffWitness live interception; Proof and Debt still work

Current Codex requires its own hook feature and trust flow before project hooks execute. DiffWitness never
approves itself; `dw protect status` stays conservative until a live Codex hook reaches Protect.

A blocked or observed runtime action is not proof that the final software works. DiffWitness verifies the
""",
    )

    replace_once(
        "CHANGELOG.md",
        """- Hash-linked bounded Protect receipts under local Git metadata, with no intentional raw command, source, prompt, raw event, or raw session-id persistence.
""",
        """- Hash-linked bounded Protect receipts under local Git metadata, with no intentional raw command, source, prompt, raw event, or raw session-id persistence; a single bounded provider-activation receipt can establish that a configured live hook actually ran without creating a risk finding.
""",
    )
    replace_once(
        "CHANGELOG.md",
        """### Hardened

- Protect `off` installs no runtime interception hook; disabling builtin Protect removes only DiffWitness-managed hooks and preserves unrelated agent configuration.
""",
        """### Hardened

- Protect receipt appends use a dependency-free inter-process lock and refuse to silently extend a damaged/tampered chain.
- Codex readiness is fail-closed: an installed hook file is not reported ready until a live Codex hook has actually invoked Protect, and DiffWitness never writes/bypasses Codex project or hook trust on the user's behalf.
- Protect `off` installs no runtime interception hook; disabling builtin Protect removes only DiffWitness-managed hooks and preserves unrelated agent configuration.
""",
    )
    replace_once(
        "CHANGELOG.md",
        """- Builtin Protect currently targets supported Claude Code / Codex hook surfaces; generic agents remain fully supported through the independent `dw guard -- <agent>` proof boundary.
""",
        """- Builtin Protect currently targets supported Claude Code / Codex hook surfaces; generic agents remain fully supported through the independent `dw guard -- <agent>` proof boundary. Current Codex hook execution remains subject to Codex's own feature, repository-trust, and per-hook trust controls.
""",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
