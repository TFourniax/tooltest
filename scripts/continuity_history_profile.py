"""Bounded PM012 diagnostic, never a performance acceptance result."""
from __future__ import annotations
import cProfile
import hashlib
import io
import json
from pathlib import Path
import platform
import pstats
import subprocess
import tempfile

from continuity_bench import _event, _repo
from diffwitness.continuity_events import append_project_events, continuity_paths, read_project_events
from diffwitness.continuity_state import rebuild_state


def main():
    count = 100_000
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    print(json.dumps({"classification": "DIAGNOSTIC", "human_executed": False,
                      "events": count, "batch_size": 2000, "checkout_sha": actual,
                      "python": platform.python_version(), "platform": platform.platform()}), flush=True)
    with tempfile.TemporaryDirectory(prefix="dw-history-profile-") as temporary:
        repo = _repo(Path(temporary))
        for start in range(0, count, 2000):
            append_project_events(repo=repo, events=[_event(i, count) for i in range(start, min(count, start + 2000))])
        path = continuity_paths(repo).events
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        for name, call in (("verify", lambda: len(read_project_events(path))),
                           ("rebuild", lambda: rebuild_state(repo, include_structure=True))):
            profile = cProfile.Profile()
            result = profile.runcall(call)
            if name == "verify":
                assert result == count, (result, count)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == original
            output = io.StringIO()
            pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(35)
            print(f"PM012 PROFILE {name}\n{output.getvalue()}", flush=True)
            profile.dump_stats(f"continuity-100k-{name}.pstats")
        print(json.dumps({"classification": "DIAGNOSTIC", "completed": True,
                          "journal_sha256": original, "journal_bytes": path.stat().st_size()}), flush=True)


if __name__ == "__main__":
    main()
