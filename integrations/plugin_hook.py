from __future__ import annotations

import os
import sys
from pathlib import Path


def _plugin_root() -> Path:
    explicit = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parents[1]


ROOT = _plugin_root()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from diffwitness.proof_cli import main  # noqa: E402


def run() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"session-start", "session-stop"}:
        print("DiffWitness plugin hook requires session-start or session-stop", file=sys.stderr)
        return 2
    command = sys.argv[1]
    policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
    args = [command]
    if command == "session-stop":
        args += ["--policy", policy]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
