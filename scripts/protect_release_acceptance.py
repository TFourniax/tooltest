from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dw", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def json_run(repo: Path, *args: str) -> dict:
    result = run(repo, *args, "--json")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError(f"expected object JSON from {' '.join(args)}")
    return value


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dw-protect-release-") as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.email", "protect@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Protect Acceptance"], cwd=repo, check=True)
        (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        claude_dir = repo / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.local.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "foreign-hook check",
                                        "timeout": 2,
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        initial = json_run(repo, "protect", "status")
        assert initial["mode"] == "off", initial
        assert initial["health"] == "off", initial

        detection = json_run(repo, "protect", "detect")
        assert detection["otherHookActivityDetected"] is True, detection
        assert detection["externalHarnessDetected"] is False, detection

        enabled = json_run(repo, "protect", "enable", "--force")
        assert enabled["mode"] == "builtin", enabled
        assert enabled["health"] == "ready", enabled
        rendered = settings.read_text(encoding="utf-8")
        assert "foreign-hook check" in rendered
        assert "protect-pre" in rendered
        assert "protect-post" in rendered

        disabled = json_run(repo, "protect", "disable")
        assert disabled["mode"] == "off", disabled
        rendered = settings.read_text(encoding="utf-8")
        assert "foreign-hook check" in rendered
        assert "protect-pre" not in rendered
        assert "protect-post" not in rendered

        delegated = json_run(repo, "protect", "use", "external")
        assert delegated["mode"] == "external", delegated
        assert delegated["health"] == "delegated", delegated
        rendered = settings.read_text(encoding="utf-8")
        assert "foreign-hook check" in rendered
        assert "protect-pre" not in rendered

        final = json_run(repo, "protect", "disable")
        assert final["mode"] == "off", final
        assert json_run(repo, "protect", "status")["mode"] == "off"

    print("Protect installed-artifact acceptance PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
