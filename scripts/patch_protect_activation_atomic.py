from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    path = "src/diffwitness/protect.py"

    replace_once(
        path,
        '''            "adapters": [],\n            "managedHooks": {},\n        }\n''',
        '''            "adapters": [],\n            "managedHooks": {},\n            "providerActivation": {},\n        }\n''',
    )

    replace_once(
        path,
        '''    adapters = [\n        str(item)\n        for item in raw.get("adapters", [])\n        if str(item) in SUPPORTED_ADAPTERS\n    ]\n    return {\n''',
        '''    adapters = [\n        str(item)\n        for item in raw.get("adapters", [])\n        if str(item) in SUPPORTED_ADAPTERS\n    ]\n    activation_raw = raw.get("providerActivation")\n    provider_activation = {\n        str(provider): str(seen_at)\n        for provider, seen_at in activation_raw.items()\n        if str(provider) in SUPPORTED_ADAPTERS and isinstance(seen_at, str)\n    } if isinstance(activation_raw, Mapping) else {}\n    return {\n''',
    )

    replace_once(
        path,
        '''        "adapters": list(dict.fromkeys(adapters)),\n        "managedHooks": raw.get("managedHooks") if isinstance(raw.get("managedHooks"), dict) else {},\n    }\n''',
        '''        "adapters": list(dict.fromkeys(adapters)),\n        "managedHooks": raw.get("managedHooks") if isinstance(raw.get("managedHooks"), dict) else {},\n        "providerActivation": provider_activation,\n    }\n''',
    )

    replace_once(
        path,
        '''        "managedHooks": managed,\n        "diffwitnessCommand": dw_command,\n        "externalDetection": detection,\n        "updatedAt": _now(),\n    }\n    _write_json(_config_path(repo), config)\n    return protect_status(repo)\n''',
        '''        "managedHooks": managed,\n        "providerActivation": {},\n        "diffwitnessCommand": dw_command,\n        "externalDetection": detection,\n        "updatedAt": _now(),\n    }\n    with _receipt_lock(repo):\n        _write_json(_config_path(repo), config)\n    return protect_status(repo)\n''',
    )

    replace_once(
        path,
        '''    adapters = list(config.get("adapters") or [])\n    receipt_values, _ = _iter_receipts(repo)\n    enabled_at = str(config.get("updatedAt") or "")\n    active_providers = {\n        str(item.get("provider"))\n        for item in receipt_values\n        if str(item.get("provider")) in SUPPORTED_ADAPTERS\n        and (not enabled_at or str(item.get("ts") or "") >= enabled_at)\n    }\n''',
        '''    adapters = list(config.get("adapters") or [])\n    enabled_at = str(config.get("updatedAt") or "")\n    provider_activation = config.get("providerActivation")\n    active_providers = {\n        str(provider)\n        for provider, seen_at in provider_activation.items()\n        if str(provider) in SUPPORTED_ADAPTERS\n        and isinstance(seen_at, str)\n        and (not enabled_at or seen_at >= enabled_at)\n    } if isinstance(provider_activation, Mapping) else set()\n''',
    )

    old_append = '''def append_receipt(\n    repo: Path,\n    *,\n    payload: Mapping[str, Any],\n    phase: str,\n    decision: str,\n    category: str,\n    rule: str,\n    message: str,\n    path: str | None = None,\n) -> dict[str, Any]:\n    receipt_path = _receipts_path(repo)\n    receipt_path.parent.mkdir(parents=True, exist_ok=True)\n    session = str(\n        payload.get("session_id")\n        or payload.get("sessionId")\n        or payload.get("conversation_id")\n        or payload.get("conversationId")\n        or "unknown"\n    )\n    tool = str(\n        payload.get("tool_name")\n        or payload.get("toolName")\n        or payload.get("tool")\n        or "unknown"\n    )[:80]\n    provider = str(payload.get("provider") or payload.get("agent") or "unknown")[:40]\n    with _receipt_lock(repo):\n        previous = _last_receipt_hash(receipt_path)\n        stable = {\n            "schema": RECEIPT_SCHEMA,\n            "ts": _now(),\n            "sessionDigest": hashlib.sha256(session.encode("utf-8")).hexdigest()[:16],\n            "provider": provider,\n            "phase": phase[:24],\n            "decision": decision[:24],\n            "category": category[:80],\n            "rule": rule[:100],\n            "tool": tool,\n            "path": path[:300] if isinstance(path, str) else None,\n            "message": message[:240],\n            "prev": previous,\n        }\n        digest = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()\n        receipt = {**stable, "id": "dwpr_" + digest[:20], "hash": digest}\n        try:\n            with receipt_path.open("a", encoding="utf-8", newline="\\n") as handle:\n                handle.write(_canonical(receipt) + "\\n")\n        except OSError as exc:\n            raise ProtectError(f"cannot append Protect receipt: {exc}") from exc\n    return receipt\n'''
    new_append = '''def _append_receipt_locked(\n    repo: Path,\n    *,\n    payload: Mapping[str, Any],\n    phase: str,\n    decision: str,\n    category: str,\n    rule: str,\n    message: str,\n    path: str | None = None,\n) -> dict[str, Any]:\n    receipt_path = _receipts_path(repo)\n    receipt_path.parent.mkdir(parents=True, exist_ok=True)\n    session = str(\n        payload.get("session_id")\n        or payload.get("sessionId")\n        or payload.get("conversation_id")\n        or payload.get("conversationId")\n        or "unknown"\n    )\n    tool = str(\n        payload.get("tool_name")\n        or payload.get("toolName")\n        or payload.get("tool")\n        or "unknown"\n    )[:80]\n    provider = str(payload.get("provider") or payload.get("agent") or "unknown")[:40]\n    previous = _last_receipt_hash(receipt_path)\n    stable = {\n        "schema": RECEIPT_SCHEMA,\n        "ts": _now(),\n        "sessionDigest": hashlib.sha256(session.encode("utf-8")).hexdigest()[:16],\n        "provider": provider,\n        "phase": phase[:24],\n        "decision": decision[:24],\n        "category": category[:80],\n        "rule": rule[:100],\n        "tool": tool,\n        "path": path[:300] if isinstance(path, str) else None,\n        "message": message[:240],\n        "prev": previous,\n    }\n    digest = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()\n    receipt = {**stable, "id": "dwpr_" + digest[:20], "hash": digest}\n    try:\n        with receipt_path.open("a", encoding="utf-8", newline="\\n") as handle:\n            handle.write(_canonical(receipt) + "\\n")\n    except OSError as exc:\n        raise ProtectError(f"cannot append Protect receipt: {exc}") from exc\n    return receipt\n\n\ndef append_receipt(\n    repo: Path,\n    *,\n    payload: Mapping[str, Any],\n    phase: str,\n    decision: str,\n    category: str,\n    rule: str,\n    message: str,\n    path: str | None = None,\n) -> dict[str, Any]:\n    with _receipt_lock(repo):\n        return _append_receipt_locked(\n            repo,\n            payload=payload,\n            phase=phase,\n            decision=decision,\n            category=category,\n            rule=rule,\n            message=message,\n            path=path,\n        )\n'''
    replace_once(path, old_append, new_append)

    old_mark = '''def _mark_provider_active(repo: Path, payload: Mapping[str, Any]) -> None:\n    provider = str(payload.get("provider") or payload.get("agent") or "").strip().lower()\n    if provider not in SUPPORTED_ADAPTERS:\n        return\n    config = load_protect_config(repo)\n    if config.get("mode") != "builtin" or provider not in set(config.get("adapters") or []):\n        return\n    enabled_at = str(config.get("updatedAt") or "")\n    values, _ = _iter_receipts(repo)\n    if any(\n        str(item.get("provider")) == provider\n        and (not enabled_at or str(item.get("ts") or "") >= enabled_at)\n        for item in values\n    ):\n        return\n    append_receipt(\n        repo,\n        payload=payload,\n        phase="runtime",\n        decision="active",\n        category="runtime",\n        rule="hook-live",\n        message="The configured provider invoked DiffWitness Protect.",\n    )\n'''
    new_mark = '''def _mark_provider_active(repo: Path, payload: Mapping[str, Any]) -> None:\n    provider = str(payload.get("provider") or payload.get("agent") or "").strip().lower()\n    if provider not in SUPPORTED_ADAPTERS:\n        return\n    with _receipt_lock(repo):\n        config = load_protect_config(repo)\n        if config.get("mode") != "builtin" or provider not in set(config.get("adapters") or []):\n            return\n        enabled_at = str(config.get("updatedAt") or "")\n        activation = dict(config.get("providerActivation") or {})\n        seen_at = activation.get(provider)\n        if isinstance(seen_at, str) and (not enabled_at or seen_at >= enabled_at):\n            return\n        receipt = _append_receipt_locked(\n            repo,\n            payload=payload,\n            phase="runtime",\n            decision="active",\n            category="runtime",\n            rule="hook-live",\n            message="The configured provider invoked DiffWitness Protect.",\n        )\n        activation[provider] = str(receipt["ts"])\n        _write_json(_config_path(repo), {**config, "providerActivation": activation})\n'''
    replace_once(path, old_mark, new_mark)

    tests = "tests/test_protect.py"
    test_anchor = '''    def test_status_is_bounded_and_contains_no_raw_agent_data(self):\n'''
    test_add = '''    def test_parallel_first_codex_hooks_record_one_durable_activation(self):\n        with tempfile.TemporaryDirectory() as td:\n            repo = self.repo(Path(td))\n            (repo / ".codex").mkdir()\n            with mock.patch("diffwitness.protect.shutil.which", side_effect=lambda name: "/usr/bin/codex" if name == "codex" else None):\n                enabled = set_protect_mode(repo, "builtin", force=True)\n            self.assertEqual(enabled["health"], "degraded")\n\n            def safe_hook(index: int) -> None:\n                result = evaluate_pre_tool(\n                    repo,\n                    {\n                        "provider": "codex",\n                        "session_id": f"activation-{index}",\n                        "tool_name": "shell",\n                        "tool_input": {"command": "git status --short"},\n                    },\n                )\n                self.assertIsNone(result)\n\n            with ThreadPoolExecutor(max_workers=8) as pool:\n                list(pool.map(safe_hook, range(40)))\n\n            summary = protection_summary(repo)\n            self.assertTrue(summary["integrity"])\n            self.assertEqual(summary["count"], 1)\n            self.assertEqual(summary["decisions"].get("active"), 1)\n            config = load_protect_config(repo)\n            self.assertIn("codex", config["providerActivation"])\n            ready = protect_status(repo)\n            self.assertTrue(ready["adapters"]["codex"]["activeSeen"])\n            self.assertTrue(ready["adapters"]["codex"]["ready"])\n\n            with mock.patch("diffwitness.protect._iter_receipts", return_value=([], True)):\n                durable = protect_status(repo)\n            self.assertTrue(durable["adapters"]["codex"]["activeSeen"])\n            self.assertTrue(durable["adapters"]["codex"]["ready"])\n\n'''
    replace_once(tests, test_anchor, test_add + test_anchor)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
