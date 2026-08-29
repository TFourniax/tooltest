from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


EXPLANATION_SCHEMA = "idleproof.explanation.v2"
LLM_CONTEXT_SCHEMA = "idleproof.llm-context.v1"
DEFAULT_SOUL_MAX_CHARS = 8_000
DEFAULT_LLM_MAX_CHARS = 24_000

_CATEGORY_IMPACT = {
    "evidence": "The change needs stronger executable evidence before its behavior is fully demonstrated.",
    "test": "The change leaves a test obligation or an uncovered behavior that is worth verifying.",
    "complexity": "The change increases implementation complexity, which can make later changes harder to reason about.",
    "redundancy": "The change introduces or exposes duplicated implementation that can drift over time.",
    "dependency": "The change affects dependency boundaries, so availability, upgrades, or compatibility may matter.",
    "architecture": "The change affects an architectural boundary or responsibility split.",
    "security": "The change touches a security-sensitive behavior and deserves explicit verification.",
    "migration": "The change affects persisted data or a migration path and may need rollout or rollback care.",
    "knowledge": "The change leaves knowledge that is not yet captured strongly enough for future maintainers.",
    "unverified_change": "Part of the change is not yet backed by sufficient deterministic or causal evidence.",
}

_SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
_MEASUREMENT_CONFIDENCE = {
    "causal": "verified",
    "deterministic": "verified",
    "historical": "supported",
    "heuristic": "advisory",
}


@dataclass(frozen=True, slots=True)
class ManagedPlanPolicy:
    plan: str
    monthly_limit: int | None
    diffwitness_managed_allowed: bool


_MANAGED_POLICIES = {
    "free": ManagedPlanPolicy("free", 0, False),
    "community": ManagedPlanPolicy("community", 0, False),
    "builder": ManagedPlanPolicy("builder", 500, True),
    "pro": ManagedPlanPolicy("pro", 1_200, True),
    "team": ManagedPlanPolicy("team", 1_000, True),
    "enterprise": ManagedPlanPolicy("enterprise", None, True),
}


def managed_plan_policy(plan: str) -> ManagedPlanPolicy:
    """Return the hard managed-inference policy for one plan.

    Unknown plans fail closed to Community semantics. This is deliberate: a billing/configuration
    typo must never silently unlock inference paid by DiffWitness.
    """

    normalized = str(plan or "community").strip().lower()
    return _MANAGED_POLICIES.get(normalized, _MANAGED_POLICIES["community"])


def managed_inference_allowed(*, plan: str, used: int = 0, seats: int = 1) -> bool:
    policy = managed_plan_policy(plan)
    if not policy.diffwitness_managed_allowed:
        return False
    if policy.monthly_limit is None:
        return True
    safe_used = max(0, int(used or 0))
    multiplier = max(1, int(seats or 1)) if policy.plan == "team" else 1
    return safe_used < policy.monthly_limit * multiplier


def resolve_inference_mode(
    *,
    requested: str,
    plan: str,
    managed_used: int = 0,
    seats: int = 1,
) -> str:
    """Resolve one requested explanation mode without any chargeable hidden fallback.

    User-owned routes are returned untouched. Managed AI is granted only when the plan permits it
    and quota remains. Otherwise the deterministic renderer is selected. In particular, a free
    user can never be upgraded to managed inference by this function.
    """

    mode = str(requested or "deterministic").strip().lower().replace("_", "-")
    aliases = {
        "none": "deterministic",
        "no-ai": "deterministic",
        "agent": "agent-session",
        "session": "agent-session",
        "ollama": "local",
        "lm-studio": "local",
        "byok": "user-provider",
        "openrouter": "user-provider",
        "direct": "user-provider",
        "custom": "custom-endpoint",
        "cloud": "managed",
        "diffwitness-cloud": "managed",
    }
    mode = aliases.get(mode, mode)
    user_owned = {"deterministic", "agent-session", "local", "user-provider", "custom-endpoint"}
    if mode in user_owned:
        return mode
    if mode == "managed" and managed_inference_allowed(plan=plan, used=managed_used, seats=seats):
        return "managed"
    return "deterministic"


def _safe_text(value: Any, *, max_chars: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def _path_kind(path: str, *, is_test: bool = False) -> str:
    lowered = path.lower()
    if is_test or any(token in lowered for token in ("/test/", "/tests/", "__tests__", ".test.", ".spec.")):
        return "test"
    if lowered.endswith((".md", ".mdx", ".rst", ".adoc")) or lowered.startswith(("docs/", "doc/")):
        return "documentation"
    if lowered.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".lock")):
        return "configuration"
    return "production"


def _file_fact(file_patch: Any) -> dict[str, Any]:
    path = _safe_text(getattr(file_patch, "path", "<unknown>"), max_chars=320)
    hunks = list(getattr(file_patch, "hunks", []) or [])
    additions = sum(max(0, int(getattr(hunk, "additions", 0) or 0)) for hunk in hunks)
    deletions = sum(max(0, int(getattr(hunk, "deletions", 0) or 0)) for hunk in hunks)
    return {
        "path": path,
        "kind": _path_kind(path, is_test=bool(getattr(file_patch, "is_test", False))),
        "additions": additions,
        "deletions": deletions,
        "binary": bool(getattr(file_patch, "binary", False)),
        "structural": bool(getattr(file_patch, "structural", False)),
    }


def _signal_dict(signal: Any) -> dict[str, Any]:
    if isinstance(signal, Mapping):
        return dict(signal)
    to_dict = getattr(signal, "to_dict", None)
    return dict(to_dict()) if callable(to_dict) else {}


def _signal_fact(signal: Any) -> dict[str, Any]:
    raw = _signal_dict(signal)
    severity = str(raw.get("severity") or "info").lower()
    measurement = str(raw.get("measurement") or "heuristic").lower()
    path = raw.get("path") if isinstance(raw.get("path"), str) else None
    line = raw.get("line") if isinstance(raw.get("line"), int) else None
    end_line = raw.get("end_line") if isinstance(raw.get("end_line"), int) else None
    location = None
    if path:
        location = path
        if line:
            location += f":{line}"
            if end_line and end_line != line:
                location += f"-{end_line}"
    category = str(raw.get("category") or "unverified_change")
    verification = raw.get("verification") if isinstance(raw.get("verification"), Mapping) else {}
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), Mapping) else {}
    return {
        "id": _safe_text(raw.get("debt_id") or raw.get("rule_id") or "signal", max_chars=80),
        "rule": _safe_text(raw.get("rule_id") or "unknown", max_chars=120),
        "category": category,
        "severity": severity,
        "measurement": measurement,
        "confidence": _MEASUREMENT_CONFIDENCE.get(measurement, "advisory"),
        "title": _safe_text(raw.get("title") or category.replace("_", " ").title(), max_chars=240),
        "explanation": _safe_text(raw.get("explanation") or _CATEGORY_IMPACT.get(category) or "This change deserves review.", max_chars=900),
        "location": _safe_text(location, max_chars=420) if location else None,
        "points": max(0, int(raw.get("points") or 0)) if not isinstance(raw.get("points"), bool) else 0,
        "verification": {str(key): value for key, value in verification.items() if isinstance(value, (str, int, float, bool, type(None)))},
        "evidence": {str(key): value for key, value in evidence.items() if isinstance(value, (str, int, float, bool, type(None)))},
    }


def _proof_fact(envelope: Mapping[str, Any]) -> dict[str, Any]:
    proof = envelope.get("proof") if isinstance(envelope.get("proof"), Mapping) else {}
    claim = str(proof.get("claim") or "unknown")
    accepted = bool(proof.get("accepted"))
    if accepted and claim == "causal":
        explanation = "Executable evidence demonstrates that the candidate change causes the observed passing behavior."
    elif accepted and claim == "preservation":
        explanation = "Executable evidence demonstrates that the relevant behavior remains preserved after the change."
    elif accepted and claim in {"not-required", "validation"}:
        explanation = "DiffWitness accepted the change under the applicable deterministic validation boundary."
    else:
        explanation = "DiffWitness has not established a fully accepted proof claim for this change."
    return {
        "claim": claim,
        "accepted": accepted,
        "certificate_id": _safe_text(proof.get("certificate_id"), max_chars=160) or None,
        "explanation": explanation,
    }


def _what_changed(file_facts: list[dict[str, Any]]) -> list[str]:
    if not file_facts:
        return ["No production-code mutation was detected in the captured change."]
    by_kind: dict[str, int] = {}
    for item in file_facts:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    additions = sum(int(item["additions"]) for item in file_facts)
    deletions = sum(int(item["deletions"]) for item in file_facts)
    parts = [f"{count} {kind} file{'s' if count != 1 else ''}" for kind, count in sorted(by_kind.items())]
    result = [f"The captured change touches {len(file_facts)} file(s): {', '.join(parts)} ({additions} added / {deletions} removed lines)."]
    important = [item["path"] for item in file_facts if item["kind"] == "production"][:6]
    if important:
        result.append("Main production scope: " + ", ".join(important) + ("." if len(important) < 6 else "…"))
    if any(item["binary"] for item in file_facts):
        result.append("At least one binary change is present; IdleProof can describe its scope but cannot infer binary semantics from text.")
    return result


def _why_it_matters(proof: Mapping[str, Any], signals: list[dict[str, Any]]) -> list[str]:
    result = [str(proof.get("explanation") or "")]
    seen: set[str] = set()
    for signal in signals:
        category = str(signal.get("category") or "")
        if category in seen:
            continue
        seen.add(category)
        impact = _CATEGORY_IMPACT.get(category)
        if impact:
            result.append(impact)
        if len(result) >= 5:
            break
    return [item for item in result if item]


def _verification_steps(signals: list[dict[str, Any]], proof: Mapping[str, Any]) -> list[str]:
    steps: list[str] = []
    if not bool(proof.get("accepted")):
        steps.append("Do not treat the change as fully proven until DiffWitness reports an accepted proof claim.")
    for signal in signals:
        verification = signal.get("verification") if isinstance(signal.get("verification"), Mapping) else {}
        command = verification.get("command")
        if isinstance(command, str) and command.strip():
            steps.append("Run: " + _safe_text(command, max_chars=360))
        elif signal.get("category") == "test":
            target = signal.get("location") or signal.get("title")
            steps.append("Add or run a focused test for " + _safe_text(target, max_chars=280) + ".")
        elif signal.get("severity") in {"critical", "high"}:
            steps.append("Review the high-impact finding: " + _safe_text(signal.get("title"), max_chars=300) + ".")
        if len(steps) >= 6:
            break
    if not steps:
        steps.append("No additional verification action was derived beyond the accepted DiffWitness evidence.")
    # Preserve order while removing duplicate suggestions.
    return list(dict.fromkeys(steps))


def build_deterministic_explanation(
    *,
    envelope: Mapping[str, Any],
    file_patches: Iterable[Any] = (),
    debt_signals: Iterable[Any] = (),
) -> dict[str, Any]:
    """Build a high-value IdleProof explanation with no model, network, or paid service.

    Every factual claim is derived from the exact-bound DiffWitness envelope, Git patch metadata, or
    Debt Sensor output. Heuristic sensor claims remain visibly advisory instead of being promoted to
    facts. This renderer is the baseline product, not an error fallback.
    """

    file_facts = [_file_fact(item) for item in file_patches]
    signals = [_signal_fact(item) for item in debt_signals]
    signals.sort(
        key=lambda item: (
            -_SEVERITY_ORDER.get(str(item.get("severity")), 0),
            0 if item.get("confidence") == "verified" else 1,
            str(item.get("category")),
            str(item.get("location") or ""),
        )
    )
    proof = _proof_fact(envelope)
    accepted = bool(proof["accepted"])
    verified_signals = sum(1 for item in signals if item["confidence"] == "verified")
    advisory_signals = len(signals) - verified_signals
    confidence = "verified" if accepted and advisory_signals == 0 else "mixed" if accepted or verified_signals else "advisory"

    return {
        "schema": EXPLANATION_SCHEMA,
        "source": "deterministic",
        "change_id": _safe_text(envelope.get("change_id"), max_chars=160) or None,
        "confidence": confidence,
        "proof": proof,
        "summary": {
            "files": len(file_facts),
            "additions": sum(int(item["additions"]) for item in file_facts),
            "deletions": sum(int(item["deletions"]) for item in file_facts),
            "findings": len(signals),
            "verified_findings": verified_signals,
            "advisory_findings": advisory_signals,
        },
        "what_changed": _what_changed(file_facts),
        "why_it_matters": _why_it_matters(proof, signals),
        "findings": signals[:24],
        "verify_next": _verification_steps(signals, proof),
        "files": file_facts[:40],
        "provenance": {
            "code_uploaded": False,
            "llm_used": False,
            "network_required": False,
            "claims_are_evidence_bounded": True,
        },
    }


def _soul_candidates(repo: Path) -> tuple[Path, ...]:
    return (
        repo / ".diffwitness" / "soul.md",
        repo / ".idleproof" / "soul.md",
        repo / "soul.md",
    )


def load_soul(repo: Path, *, max_chars: int = DEFAULT_SOUL_MAX_CHARS) -> dict[str, Any] | None:
    """Load optional local style guidance without ever turning it into factual evidence."""

    for path in _soul_candidates(repo):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # A soul is presentation guidance only. Bound it aggressively so it can never dominate the
        # evidence context or create unbounded model cost.
        text = text.strip()[: max(0, int(max_chars))]
        if text:
            try:
                relative = path.relative_to(repo).as_posix()
            except ValueError:
                relative = path.name
            return {"path": relative, "instructions": text}
    return None


def build_llm_context(
    explanation: Mapping[str, Any],
    *,
    soul: Mapping[str, Any] | None = None,
    max_chars: int = DEFAULT_LLM_MAX_CHARS,
) -> dict[str, Any]:
    """Create the only payload a presentation LLM needs.

    Raw source code, prompts and repository-wide context are intentionally absent. The model's job
    is to rewrite evidence-backed facts, never to discover the facts itself.
    """

    allowed = {
        "change_id": explanation.get("change_id"),
        "confidence": explanation.get("confidence"),
        "proof": explanation.get("proof"),
        "summary": explanation.get("summary"),
        "what_changed": explanation.get("what_changed"),
        "why_it_matters": explanation.get("why_it_matters"),
        "findings": explanation.get("findings"),
        "verify_next": explanation.get("verify_next"),
        "files": explanation.get("files"),
    }
    payload: dict[str, Any] = {
        "schema": LLM_CONTEXT_SCHEMA,
        "role": "You are a presentation layer. Rephrase only the supplied evidence-backed facts. Do not add behavior, risk, intent, causality, or recommendations not present in the facts.",
        "facts": allowed,
    }
    if soul:
        payload["style"] = {
            "instructions": _safe_text(soul.get("instructions"), max_chars=DEFAULT_SOUL_MAX_CHARS),
            "note": "Style guidance may change tone and vocabulary only; it cannot override evidence or safety constraints.",
        }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > max_chars:
        # First shed optional detail rather than truncate JSON or facts mid-field.
        facts = dict(allowed)
        facts["findings"] = list(facts.get("findings") or [])[:8]
        facts["files"] = list(facts.get("files") or [])[:12]
        payload["facts"] = facts
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > max_chars:
        # The deterministic explanation remains complete; the LLM gets a bounded synopsis.
        payload["facts"] = {
            "change_id": explanation.get("change_id"),
            "confidence": explanation.get("confidence"),
            "proof": explanation.get("proof"),
            "summary": explanation.get("summary"),
            "what_changed": list(explanation.get("what_changed") or [])[:3],
            "why_it_matters": list(explanation.get("why_it_matters") or [])[:3],
            "verify_next": list(explanation.get("verify_next") or [])[:4],
        }
    return payload


def write_explanation_artifact(
    *,
    repo: Path,
    envelope: Mapping[str, Any],
    file_patches: Iterable[Any] = (),
    debt_signals: Iterable[Any] = (),
) -> Path:
    explanation = build_deterministic_explanation(
        envelope=envelope,
        file_patches=file_patches,
        debt_signals=debt_signals,
    )
    output = repo / ".git" / "diffwitness" / "idleproof-explanation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_suffix(".json.tmp")
    staged.write_text(json.dumps(explanation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    staged.replace(output)
    return output


def explanation_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw explain",
        description="Show the latest evidence-backed IdleProof explanation without using a LLM.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from .gitops import repo_root

    root = repo_root(args.repo)
    path = root / ".git" / "diffwitness" / "idleproof-explanation.json"
    if not path.is_file():
        print("No captured IdleProof explanation yet. Run a guarded/IDE task first.")
        return 2
    try:
        explanation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"IdleProof explanation cannot be read: {exc}")
        return 2
    if args.json:
        print(json.dumps(explanation, indent=2, ensure_ascii=False))
        return 0
    print("IdleProof · evidence-backed explanation")
    print(f"Confidence: {explanation.get('confidence', 'unknown')}")
    for title, key in (("What changed", "what_changed"), ("Why it matters", "why_it_matters"), ("Verify next", "verify_next")):
        print(f"\n{title}")
        for item in explanation.get(key) or []:
            print(f"- {item}")
    findings = explanation.get("findings") or []
    if findings:
        print("\nEvidence-backed findings")
        for item in findings[:12]:
            location = f" · {item['location']}" if item.get("location") else ""
            print(f"- [{item.get('confidence', 'advisory')}] {item.get('title', 'Finding')}{location}")
    print("\nNo LLM or paid API was used for this explanation.")
    return 0
