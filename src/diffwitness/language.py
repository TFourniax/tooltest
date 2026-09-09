"""Explicit human presentation language; never infer it from the host locale."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path

from .gitops import git_metadata_path, repo_root

LANGUAGES = ("en", "fr")
_current: ContextVar[str] = ContextVar("diffwitness_language", default="en")


def tr(english: str, french: str) -> str:
    """Select human wording only. Never call while constructing machine facts."""
    return french if _current.get() == "fr" else english


def saved_language(repo: Path) -> str:
    path = git_metadata_path(repo, "diffwitness/ui-preferences.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "en"
    return value.get("language") if isinstance(value, dict) and value.get("language") in LANGUAGES else "en"


@contextmanager
def presentation(language: str):
    if language not in LANGUAGES:
        raise ValueError("language must be en or fr; use `dw --language en <command>` or `dw language fr`")
    token = _current.set(language)
    try:
        yield
    finally:
        _current.reset(token)


def language_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw language", description=tr(
        "Show or explicitly save this project's presentation language.",
        "Afficher ou enregistrer explicitement la langue de présentation du projet."))
    parser.add_argument("language", nargs="?", choices=LANGUAGES)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    if args.language:
        path = git_metadata_path(repo, "diffwitness/ui-preferences.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        value.update(schema="diffwitness.ui-preferences.v1", language=args.language)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    language = args.language or _current.get()
    if args.json:
        print(json.dumps({"schema": "diffwitness.language.v1", "language": language}))
    else:
        with presentation(language):
            print(tr(f"DiffWitness language: {language}", f"Langue DiffWitness : {language}"))
            print(tr("Use `dw language en|fr` to save; `dw --language en|fr <command>` for one invocation.",
                     "Enregistrer : `dw language en|fr` ; une invocation : `dw --language en|fr <commande>`."))
    return 0
