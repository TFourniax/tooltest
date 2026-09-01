from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_MAX_ANCHOR_CHARS = 1200
_MAX_FOCUS_CHARS = 1200
_MAX_HISTORY = 12
_WEAK_RE = re.compile(
    r"^(?:yes|yep|yeah|ok(?:ay)?|sure|go(?: ahead)?|continue|keep going|do it|proceed|retry|try again|"
    r"fix it|fix that|same|exactly|great|thanks?|oui|ok|d['’]?accord|vas[- ]?y|continue|continues?|poursuis|"
    r"fais[- ]?le|refais|réessaie|essaie encore|corrige(?: ça| cela)?|parfait|merci)[.!…\s]*$",
    re.IGNORECASE,
)
_PIVOT_RE = re.compile(
    r"^(?:new task|next task|different task|switch (?:to|topic)|now (?:work|let['’]?s work) on|move on to|"
    r"instead[, :]|separate task|nouvelle tâche|tâche suivante|autre tâche|changeons de (?:tâche|sujet)|passons à|"
    r"maintenant (?:travaille|travaillons) sur|autre sujet|à la place[, :])",
    re.IGNORECASE,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def is_weak_followup(prompt: str) -> bool:
    text = _compact(prompt, 320)
    if not text:
        return True
    if _WEAK_RE.fullmatch(text):
        return True
    tokens = re.findall(r"[\w-]+", text, flags=re.UNICODE)
    return len(tokens) <= 3 and len(text) <= 36 and "/" not in text and "." not in text


def is_explicit_task_pivot(prompt: str) -> bool:
    return bool(_PIVOT_RE.match(_compact(prompt, 500)))


def stable_task_id(session_id: str, ordinal: int, anchor_prompt: str) -> str:
    position = ordinal if isinstance(ordinal, int) and ordinal > 0 else 1
    anchor_digest = _sha256(str(anchor_prompt or ""))
    material = f"task-v1\0{session_id or 'default'}\0{position}\0{anchor_digest}"
    return "dwtask_" + _sha256(material)[:24]


def _session_root(repo: Path) -> Path:
    digest = _sha256(str(repo.resolve()))[:20]
    path = Path(tempfile.gettempdir()) / "diffwitness-task-sessions" / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(repo: Path, session_id: str) -> Path:
    return _session_root(repo) / (_sha256(session_id or "default")[:24] + ".json")


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema": "continuity-task-session-1", "task": None, "history": []}
    if not isinstance(value, dict) or value.get("schema") != "continuity-task-session-1":
        return {"schema": "continuity-task-session-1", "task": None, "history": []}
    if not isinstance(value.get("history"), list):
        value["history"] = []
    return value


def _snapshot(task: dict[str, Any]) -> dict[str, Any]:
    return {key: task.get(key) for key in (
        "id", "ordinal", "anchor", "anchor_chars", "anchor_sha256", "latest_focus", "latest_focus_chars",
        "latest_focus_sha256", "prompts", "started_at", "updated_at", "completed_at"
    )}


def _start(session_id: str, raw_prompt: str, ordinal: int, timestamp: str) -> dict[str, Any]:
    anchor = _compact(raw_prompt, _MAX_ANCHOR_CHARS)
    return {
        "id": stable_task_id(session_id, ordinal, raw_prompt),
        "ordinal": ordinal,
        "anchor": anchor,
        "anchor_chars": len(raw_prompt),
        "anchor_sha256": _sha256(raw_prompt),
        "latest_focus": anchor,
        "latest_focus_chars": len(raw_prompt),
        "latest_focus_sha256": _sha256(raw_prompt),
        "prompts": 1,
        "started_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
    }


def update_task_session(repo: Path, session_id: str, raw_prompt: str, *, timestamp: str | None = None) -> dict[str, Any]:
    prompt = str(raw_prompt or "")
    text = _compact(prompt, _MAX_FOCUS_CHARS)
    path = _session_path(repo, session_id)
    state = _load(path)
    if not text:
        return {"task": state.get("task"), "boundary": "none", "weak_followup": True, "path": path}
    now = timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    task = state.get("task") if isinstance(state.get("task"), dict) else None
    history = list(state.get("history") or [])
    if task is None:
        task = _start(session_id, prompt, 1, now)
        boundary = "started"
        weak = False
    elif is_explicit_task_pivot(text):
        task["completed_at"] = now
        history.append(_snapshot(task))
        history = history[-_MAX_HISTORY:]
        task = _start(session_id, prompt, int(task.get("ordinal") or 1) + 1, now)
        boundary = "pivoted"
        weak = False
    else:
        weak = is_weak_followup(text)
        task["prompts"] = max(1, int(task.get("prompts") or 1)) + 1
        task["updated_at"] = now
        task["latest_focus_chars"] = len(prompt)
        task["latest_focus_sha256"] = _sha256(prompt)
        if not weak:
            task["latest_focus"] = text
        boundary = "continued" if weak else "focused"
    state = {"schema": "continuity-task-session-1", "task": task, "history": history}
    _atomic_write(path, state)
    return {"task": task, "boundary": boundary, "weak_followup": weak, "path": path}


def task_context_query(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    anchor = _compact(str(task.get("anchor") or ""), _MAX_ANCHOR_CHARS)
    focus = _compact(str(task.get("latest_focus") or ""), _MAX_FOCUS_CHARS)
    if not focus or focus == anchor:
        return anchor
    return f"Primary task: {anchor}\nCurrent focus: {focus}"


def cleanup_task_session(repo: Path, session_id: str) -> None:
    try:
        _session_path(repo, session_id).unlink()
    except FileNotFoundError:
        pass


def task_session_path(repo: Path, session_id: str) -> Path:
    """Expose the temp path for diagnostics/tests; raw prompt text never belongs in ProjectEvent state."""
    return _session_path(repo, session_id)
