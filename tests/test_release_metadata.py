from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

from diffwitness import __version__


class ReleaseMetadataTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_python_and_plugin_versions_describe_the_same_release(self) -> None:
        project = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["version"], __version__)

        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)a(\d+)", __version__)
        self.assertIsNotNone(match, "Update the explicit PEP 440 to SemVer mapping for this release form")
        assert match is not None
        plugin_version = f"{match[1]}.{match[2]}.{match[3]}-alpha.{match[4]}"

        claude = json.loads((self.root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((self.root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads(
            (self.root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude["version"], plugin_version)
        self.assertEqual(codex["version"], plugin_version)
        self.assertEqual(marketplace["version"], plugin_version)
        self.assertEqual(marketplace["plugins"][0]["version"], plugin_version)

    def test_launch_docs_keep_native_agents_primary_and_guided_first(self) -> None:
        launch = (self.root / "docs/LAUNCH.md").read_text(encoding="utf-8")
        surfaces = (self.root / "docs/PRODUCT_SURFACES.md").read_text(encoding="utf-8")
        help_source = (self.root / "src/diffwitness/public_help.py").read_text(encoding="utf-8")
        proof_cli = (self.root / "src/diffwitness/proof_cli.py").read_text(encoding="utf-8")
        protocol = (self.root / "docs/PROOF_PROTOCOL.md").read_text(encoding="utf-8")
        guard = (self.root / "docs/GUARD.md").read_text(encoding="utf-8")
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("dw setup --agent claude", launch)
        self.assertIn("normal `claude` or `codex` use", launch)
        self.assertIn("explicit fallback", launch)
        self.assertNotIn("low-friction path is `dw guard", launch)
        self.assertIn("First run defaults to Guided", surfaces)
        self.assertNotIn("default to Technical", surfaces)
        self.assertIn("per-worktree Git metadata", help_source)
        self.assertIn("native setup is the primary workflow", proof_cli)
        self.assertNotIn('print("\\nAgent guard examples:")', proof_cli)
        self.assertNotIn("wrapper remains the reference path", protocol)
        self.assertIn("explicit fallback", protocol)
        self.assertIn("deliberate fallback", guard)
        self.assertIn("Claude Code desktop app", readme)
        self.assertIn("Codex app", readme)

    def test_distributed_hook_locations_match_local_desktop_and_cli_contracts(self) -> None:
        claude = json.loads((self.root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((self.root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(claude["hooks"], "./hooks/claude-hooks.json")
        self.assertEqual(codex["hooks"], "./hooks/codex-hooks.json")

        claude_hooks = json.loads((self.root / "hooks/claude-hooks.json").read_text(encoding="utf-8"))
        codex_hooks = json.loads((self.root / "hooks/codex-hooks.json").read_text(encoding="utf-8"))
        for provider, payload in (("claude", claude_hooks), ("codex", codex_hooks)):
            commands = [
                hook["command"]
                for groups in payload["hooks"].values()
                for group in groups
                for hook in group["hooks"]
            ]
            self.assertTrue(commands)
            self.assertTrue(all(f"--provider {provider}" in command for command in commands))

    def test_all_canonical_release_gates_requalify_main_merges(self) -> None:
        for workflow in (
            "test.yml",
            "proofbench.yml",
            "continuitybench.yml",
            "integrated-product.yml",
        ):
            text = (self.root / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
            push = re.search(r"(?m)^  push:\n    branches: \[([^\]]+)]", text)
            self.assertIsNotNone(push, f"{workflow} must select push branches explicitly")
            assert push is not None
            branches = {item.strip().strip('\"\'') for item in push[1].split(",")}
            self.assertIn("main", branches, f"{workflow} must requalify the merged main commit")


if __name__ == "__main__":
    unittest.main()
