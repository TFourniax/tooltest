"""Run the included source suite from an isolated, actual source distribution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import venv


def verify_test_inventory(root: Path, source: Path) -> None:
    expected = set(subprocess.check_output(
        ["git", "ls-files", "-z", "--", "tests"], cwd=source
    ).decode("utf-8").strip("\0").split("\0"))
    if not expected or "" in expected:
        raise ValueError("Canonical source test inventory is empty")
    actual = {item.relative_to(root).as_posix() for item in (root / "tests").rglob("*")
              if item.is_file()}
    if actual != expected:
        raise ValueError(f"Source test inventory differs: missing={sorted(expected - actual)!r}; "
                         f"extra={sorted(actual - expected)!r}")
    for name in sorted(expected):
        if (root / name).read_bytes() != (source / name).read_bytes():
            raise ValueError(f"Source distribution changed test asset: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--compare-source-root", type=Path)
    args = parser.parse_args()
    archive, log = args.archive.resolve(), args.log.resolve()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="diffwitness-sdist-") as temporary:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            roots = {PurePosixPath(item.name).parts[0] for item in members if item.name}
            if len(roots) != 1 or not all(
                (item.isfile() or item.isdir()) and not PurePosixPath(item.name).is_absolute()
                and ".." not in PurePosixPath(item.name).parts for item in members
            ):
                raise ValueError("Source archive must contain one regular directory tree")
            destination = Path(temporary).resolve()
            seen = set()
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.name).parts).resolve()
                if not target.is_relative_to(destination) or target in seen:
                    raise ValueError("Ambiguous or escaping source archive entry")
                seen.add(target)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    # Preserve executable hooks without admitting setuid or other modes.
                    target.chmod(member.mode & 0o777)
        root = Path(temporary) / roots.pop()
        tests = sorted((root / "tests").glob("test*.py"))
        if not tests or not (root / "src/diffwitness/__init__.py").is_file():
            raise ValueError("Source distribution has no usable source qualification suite")
        if args.compare_source_root:
            verify_test_inventory(root, args.compare_source_root.resolve())
        with log.open("wb") as output:
            environment = Path(temporary) / "qualification-venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            scripts = environment / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            env = {**os.environ, "PATH": str(scripts) + os.pathsep + os.environ.get("PATH", ""),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            env.pop("PYTHONPATH", None)
            # Native hook tests require entrypoints belonging to the exact source
            # under test. A wheel from a different location is intentionally refused.
            subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                            "--no-deps", "--editable", str(root)], cwd=root, env=env,
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=180)
            result = subprocess.run(
                [str(python), "-m", "unittest", "discover", "-s", "tests"],
                cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=900,
            )
        print(json.dumps({"schema": "diffwitness-source-distribution-smoke-1",
                          "classification": "MACHINE", "python": platform.python_version(), "archive": archive.name,
                          "archive_sha256": digest, "test_modules": len(tests),
                          "source_inventory_compared": args.compare_source_root is not None,
                          "checkout_used_by_suite": False, "returncode": result.returncode,
                          "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
