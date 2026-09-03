from __future__ import annotations

import ast
import unittest
from pathlib import Path


class IdleProofArchitectureInvariantTests(unittest.TestCase):
    @property
    def package_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "src" / "diffwitness"

    def imports(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_optional_user_inference_never_flows_back_into_proof_debt_or_continuity_modules(self):
        offenders: list[str] = []
        for path in sorted(self.package_root.rglob("*.py")):
            relative = path.relative_to(self.package_root).as_posix()
            if relative in {"idleproof_user_inference.py", "entry/__init__.py"}:
                continue
            imports = self.imports(path)
            if any(name.endswith("idleproof_user_inference") for name in imports):
                offenders.append(relative)
        self.assertEqual(
            offenders,
            [],
            "Optional presentation inference must remain a leaf dependency reachable only through the explicit CLI entrypoint.",
        )

    def test_authoritative_proof_path_has_no_model_or_http_client_dependency(self):
        authoritative = [
            "adaptive.py",
            "analysis.py",
            "assurance.py",
            "attestation.py",
            "change_envelope.py",
            "proof_cli.py",
            "runner.py",
            "guard.py",
        ]
        forbidden_prefixes = (
            "openai",
            "anthropic",
            "httpx",
            "requests",
            "urllib.request",
            "idleproof_user_inference",
        )
        offenders: dict[str, list[str]] = {}
        for relative in authoritative:
            path = self.package_root / relative
            self.assertTrue(path.is_file(), f"Architecture gate expected authoritative module {relative}")
            bad = sorted(name for name in self.imports(path) if name.startswith(forbidden_prefixes))
            if bad:
                offenders[relative] = bad
        self.assertEqual(
            offenders,
            {},
            "Proof/Debt authority must not acquire a network/model dependency from IdleProof presentation work.",
        )

    def test_guard_may_emit_deterministic_idleproof_but_not_call_optional_inference(self):
        source = (self.package_root / "guard.py").read_text(encoding="utf-8")
        self.assertIn("idleproof_explanation", source)
        self.assertNotIn("idleproof_user_inference", source)
        self.assertLess(source.index("build_change_envelope"), source.index("idleproof_explanation"))

    def test_user_owned_cache_stays_in_git_metadata_not_project_source(self):
        source = (self.package_root / "idleproof_user_inference.py").read_text(encoding="utf-8")
        self.assertIn('git_metadata_path(repo, "diffwitness/idleproof-ai-cache.json")', source)
        self.assertNotIn('repo / ".idleproof" / "idleproof-ai-cache.json"', source)


if __name__ == "__main__":
    unittest.main()
