from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from .gitops import repo_root
from .idleproof_explanation import build_llm_context, load_current_explanation, load_soul


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/v1/chat/completions"
MAX_CONTEXT_CHARS = 24_000
MAX_RESPONSE_BYTES = 96_000
TIMEOUT_SECONDS = 20.0
MAX_OUTPUT_TOKENS = 800
CACHE_SCHEMA = "idleproof.user-ai-cache.v1"
MAX_CACHE_ENTRIES = 16
MAX_CACHE_BYTES = 1_000_000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class UserInferenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PresentationUnit:
    id: str
    section: str
    original: str


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward a user-owned credential through an HTTP redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise UserInferenceError("Inference endpoint attempted an HTTP redirect; refusing to forward credentials.")


def _text(value: Any, max_chars: int = 1_600) -> str:
    cleaned = _CONTROL_CHARS.sub("", str(value or ""))
    normalized = " ".join(cleaned.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 1)].rstrip() + "…"


def _string_list(value: Any, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_text(raw) for raw in value[:max_items]) if item]


def presentation_units(context: Mapping[str, Any]) -> list[PresentationUnit]:
    facts = context.get("facts") if isinstance(context.get("facts"), Mapping) else {}
    units: list[PresentationUnit] = []
    for index, value in enumerate(_string_list(facts.get("what_changed"), 6)):
        units.append(PresentationUnit(f"what_changed:{index}", "what_changed", value))
    for index, value in enumerate(_string_list(facts.get("why_it_matters"), 6)):
        units.append(PresentationUnit(f"why_it_matters:{index}", "why_it_matters", value))
    raw_findings = facts.get("findings") if isinstance(facts.get("findings"), list) else []
    for index, raw in enumerate(raw_findings[:12]):
        if not isinstance(raw, Mapping):
            continue
        title = _text(raw.get("title"), 500)
        explanation = _text(raw.get("explanation"), 1_000)
        confidence = _text(raw.get("confidence"), 40)
        location = _text(raw.get("location"), 500)
        original = " ".join(
            value
            for value in (
                title,
                explanation,
                f"Confidence: {confidence}." if confidence else "",
                f"Evidence: {location}." if location else "",
            )
            if value
        )
        if original:
            units.append(PresentationUnit(f"finding:{index}", "finding", original))
    for index, value in enumerate(_string_list(facts.get("verify_next"), 6)):
        units.append(PresentationUnit(f"verify_next:{index}", "verify_next", value))
    return units


def _unit_payload(unit: PresentationUnit) -> dict[str, str]:
    return {"id": unit.id, "section": unit.section, "original": unit.original}


def _provider_payload(*, context: Mapping[str, Any], units: list[PresentationUnit], model: str) -> bytes:
    style = context.get("style") if isinstance(context.get("style"), Mapping) else {}
    prompt = {
        "task": "Rewrite evidence-backed IdleProof units for clarity only.",
        "hard_rules": [
            'Return JSON only: {"rewrites":[{"id":"existing-id","text":"..."}]}',
            "Use only ids supplied in units. You may omit a unit but never create one.",
            "Do not add, remove, strengthen, weaken, infer, or contradict any factual claim.",
            "Do not invent behavior, risk, intent, causality, tests, recommendations, files, or evidence.",
            "Keep VERIFIED/advisory distinctions unchanged.",
            "Style preferences affect tone and vocabulary only; evidence always wins.",
        ],
        "style": _text(style.get("instructions"), 8_000) if style else None,
        "units": [_unit_payload(unit) for unit in units],
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are the optional IdleProof presentation layer. Rephrase evidence only; never discover or add facts.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 0.1,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserInferenceError("Inference endpoint must be an explicit http(s) URL.")
    if parsed.username or parsed.password:
        raise UserInferenceError("Do not put credentials in the inference URL; use an environment variable.")
    return value


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_transport_security(endpoint: str, *, api_key: str | None) -> str:
    value = _validate_url(endpoint)
    parsed = urlparse(value)
    if api_key and parsed.scheme != "https" and not _is_loopback_host(parsed.hostname):
        raise UserInferenceError("Refusing to send an API key over plaintext HTTP to a non-loopback endpoint.")
    return value


def _display_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _api_key_from_env(name: str | None, *, required: bool) -> str | None:
    if not name:
        if required:
            raise UserInferenceError("This provider requires --api-key-env pointing to your own credential.")
        return None
    normalized = name.strip()
    upper = normalized.upper()
    if upper.startswith("DIFFWITNESS_") or upper.startswith("IDLEPROOF_MANAGED_"):
        raise UserInferenceError("OSS inference cannot read DiffWitness-managed provider credentials.")
    value = os.environ.get(normalized, "").strip()
    if not value and required:
        raise UserInferenceError(f"Environment variable {normalized} is not set.")
    return value or None


def _extract_content(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise UserInferenceError("Provider returned an invalid JSON object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise UserInferenceError("Provider response has no OpenAI-compatible choice.")
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise UserInferenceError("Provider response has no textual message content.")
    return str(message["content"])


def _parse_rewrites(content: str, units: list[PresentationUnit]) -> dict[str, str]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise UserInferenceError("Provider did not return the required JSON rewrite object.") from exc
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("rewrites"), list):
        raise UserInferenceError("Provider JSON does not contain a rewrites array.")
    allowed = {unit.id for unit in units}
    accepted: dict[str, str] = {}
    for raw in parsed["rewrites"]:
        if not isinstance(raw, Mapping):
            continue
        unit_id = str(raw.get("id") or "")
        rewritten = _text(raw.get("text"))
        if unit_id in allowed and rewritten and unit_id not in accepted:
            accepted[unit_id] = rewritten
    if not accepted:
        raise UserInferenceError("Provider returned no rewrite tied to an existing evidence unit.")
    return accepted


def call_user_owned_provider(
    *,
    context: Mapping[str, Any],
    endpoint: str,
    model: str,
    api_key: str | None,
) -> dict[str, Any]:
    units = presentation_units(context)
    if not units:
        raise UserInferenceError("No evidence-backed presentation unit is available.")
    body = _provider_payload(context=context, units=units, model=model)
    if len(body) > MAX_CONTEXT_CHARS * 2:
        raise UserInferenceError("Bounded IdleProof context is still too large for user inference.")
    endpoint = _validate_transport_security(endpoint, api_key=api_key)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except UserInferenceError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UserInferenceError(f"User-owned inference endpoint failed: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UserInferenceError("User-owned inference response exceeded the safety limit.")
    try:
        provider = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserInferenceError("User-owned inference endpoint returned invalid JSON.") from exc
    rewrites = _parse_rewrites(_extract_content(provider), units)
    return {
        "source": "user-owned-ai",
        "canonical_source": "deterministic",
        "provider_endpoint": _display_endpoint(endpoint),
        "model": model,
        "units": [
            {
                "id": unit.id,
                "section": unit.section,
                "original": unit.original,
                "text": rewrites.get(unit.id, unit.original),
                "rewritten": unit.id in rewrites,
                "presentation_only": unit.id in rewrites,
            }
            for unit in units
        ],
        "cost_owner": "user",
        "diffwitness_managed_api_used": False,
    }


def _load_explanation(repo: Path) -> dict[str, Any]:
    """Load the canonical explanation only after applying the live worktree-coverage gate."""
    try:
        return load_current_explanation(repo)
    except FileNotFoundError as exc:
        raise UserInferenceError(str(exc)) from exc
    except ValueError as exc:
        raise UserInferenceError(str(exc)) from exc


def _cache_path(repo: Path) -> Path:
    return repo / ".git" / "diffwitness" / "idleproof-ai-cache.json"


def _cache_key(*, context: Mapping[str, Any], endpoint: str, model: str) -> str:
    material = {
        "context": context,
        "endpoint": _display_endpoint(endpoint),
        "model": model,
        "schema": CACHE_SCHEMA,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_cache(repo: Path) -> dict[str, Any]:
    path = _cache_path(repo)
    if not path.is_file():
        return {"schema": CACHE_SCHEMA, "entries": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": CACHE_SCHEMA, "entries": []}
    if not isinstance(value, Mapping) or value.get("schema") != CACHE_SCHEMA or not isinstance(value.get("entries"), list):
        return {"schema": CACHE_SCHEMA, "entries": []}
    return {"schema": CACHE_SCHEMA, "entries": list(value["entries"])[:MAX_CACHE_ENTRIES]}


def _cached_result(repo: Path, key: str) -> dict[str, Any] | None:
    cache = _read_cache(repo)
    for entry in cache["entries"]:
        if not isinstance(entry, Mapping) or entry.get("key") != key:
            continue
        result = entry.get("result")
        if isinstance(result, dict) and result.get("diffwitness_managed_api_used") is False:
            return {**result, "cache": "hit"}
    return None


def _store_cache(repo: Path, key: str, result: Mapping[str, Any]) -> None:
    if result.get("diffwitness_managed_api_used") is not False:
        return
    cache = _read_cache(repo)
    entries = [entry for entry in cache["entries"] if isinstance(entry, Mapping) and entry.get("key") != key]
    safe_result = dict(result)
    safe_result["cache"] = "stored"
    entries.insert(0, {"key": key, "result": safe_result})
    payload = {"schema": CACHE_SCHEMA, "entries": entries[:MAX_CACHE_ENTRIES]}
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    while len(encoded.encode("utf-8")) > MAX_CACHE_BYTES and len(payload["entries"]) > 1:
        payload["entries"].pop()
        encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_CACHE_BYTES:
        return
    path = _cache_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".json.tmp")
    try:
        staged.write_text(encoded, encoding="utf-8")
        staged.replace(path)
    except OSError:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def _print_units(result: Mapping[str, Any]) -> None:
    section_titles = {
        "what_changed": "What changed",
        "why_it_matters": "Why it matters",
        "finding": "Evidence-backed findings",
        "verify_next": "Verify next",
    }
    current = None
    for unit in result.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        section = str(unit.get("section") or "")
        if section != current:
            current = section
            print(f"\n{section_titles.get(section, section)}")
        original = _text(unit.get("original"))
        rewritten = _text(unit.get("text"))
        print(f"- {original}")
        if bool(unit.get("rewritten")) and rewritten and rewritten != original:
            print(f"  AI wording (presentation only): {rewritten}")
    cache_note = " · cached" if result.get("cache") == "hit" else ""
    print(f"\nAI provider: user-owned{cache_note}. DiffWitness managed inference cost: €0.")
    print("Canonical wording above remains the deterministic evidence-derived IdleProof result.")


def _fallback_deterministic(*, repo_arg: str, as_json: bool, reason: str) -> int:
    print(f"IdleProof AI enhancement unavailable: {reason}", file=sys.stderr)
    print("Falling back to deterministic IdleProof. No DiffWitness-paid API was contacted.", file=sys.stderr)
    from .idleproof_explanation import explanation_cli

    delegated = ["--repo", repo_arg]
    if as_json:
        delegated.append("--json")
    return explanation_cli(delegated)


def user_inference_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw explain",
        description="Explain the latest exact-bound change deterministically or with explicitly user-owned inference.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--engine",
        choices=["deterministic", "agent-session", "local", "openrouter", "custom", "managed"],
        default="deterministic",
    )
    parser.add_argument("--model", help="Model id for a user-owned local/OpenRouter/custom endpoint")
    parser.add_argument("--endpoint", help="OpenAI-compatible chat-completions URL for local/custom inference")
    parser.add_argument("--api-key-env", help="Environment variable containing your own API key; the key is never stored")
    parser.add_argument("--no-cache", action="store_true", help="Do not reuse/store user-owned presentation rewrites")
    args = parser.parse_args(argv)

    if args.engine == "deterministic":
        from .idleproof_explanation import explanation_cli

        delegated = ["--repo", args.repo]
        if args.json:
            delegated.append("--json")
        return explanation_cli(delegated)

    try:
        repo = repo_root(args.repo)
        explanation = _load_explanation(repo)
        context = build_llm_context(explanation, soul=load_soul(repo), max_chars=MAX_CONTEXT_CHARS)
        if args.engine == "managed":
            raise UserInferenceError(
                "DiffWitness Managed AI is deliberately unavailable in the OSS CLI. Paid managed inference is reserved and billed by Portal only."
            )
        if args.engine == "agent-session":
            payload = {
                "source": "agent-session-context",
                "canonical_source": "deterministic",
                "cost_owner": "user-session",
                "diffwitness_managed_api_used": False,
                "instruction": "Ask the active coding-session model to rephrase these facts only; evidence remains authoritative.",
                "context": context,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        model = (args.model or os.environ.get("IDLEPROOF_USER_MODEL") or "").strip()
        if not model:
            raise UserInferenceError("--model (or IDLEPROOF_USER_MODEL) is required for user-owned inference.")
        if args.engine == "openrouter":
            endpoint = OPENROUTER_CHAT_URL
            key_env = args.api_key_env or "OPENROUTER_API_KEY"
            api_key = _api_key_from_env(key_env, required=True)
        elif args.engine == "local":
            endpoint = args.endpoint or os.environ.get("IDLEPROOF_USER_ENDPOINT") or OLLAMA_CHAT_URL
            api_key = _api_key_from_env(args.api_key_env, required=False)
        else:
            endpoint = args.endpoint or os.environ.get("IDLEPROOF_USER_ENDPOINT") or ""
            if not endpoint:
                raise UserInferenceError("--endpoint (or IDLEPROOF_USER_ENDPOINT) is required for custom inference.")
            api_key = _api_key_from_env(args.api_key_env, required=False)

        endpoint = _validate_transport_security(endpoint, api_key=api_key)
        cache_key = _cache_key(context=context, endpoint=endpoint, model=model)
        result = None if args.no_cache else _cached_result(repo, cache_key)
        if result is None:
            result = call_user_owned_provider(context=context, endpoint=endpoint, model=model, api_key=api_key)
            if not args.no_cache:
                _store_cache(repo, cache_key, result)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_units(result)
        return 0
    except UserInferenceError as exc:
        return _fallback_deterministic(repo_arg=args.repo, as_json=args.json, reason=str(exc))
    except Exception as exc:
        return _fallback_deterministic(
            repo_arg=args.repo,
            as_json=args.json,
            reason=f"internal optional-inference error ({type(exc).__name__})",
        )


__all__ = [
    "CACHE_SCHEMA",
    "OPENROUTER_CHAT_URL",
    "OLLAMA_CHAT_URL",
    "PresentationUnit",
    "UserInferenceError",
    "call_user_owned_provider",
    "presentation_units",
    "user_inference_cli",
]
