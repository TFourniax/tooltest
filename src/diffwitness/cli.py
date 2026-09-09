from __future__ import annotations

from .language import tr

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .analysis import AnalysisError, run_analysis
from .config import load_config, write_config
from .diffing import make_mutations, parse_file_patches, supported_patch_bytes
from .github_actions import emit_annotations, is_github_actions, write_outputs, write_step_summary
from .gitops import GitError, diff_text, repo_root, resolve_ref, snapshot_worktree, resolve_analysis_base
from .reporting import build_report, render_markdown, write_json, write_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffwitness",
        description=tr('Counterfactual evidence for Git diffs: necessity, sufficiency, interactions and stability.', 'Preuves contrefactuelles des diffs Git : nécessité, suffisance, interactions et stabilité.'),
    )
    parser.add_argument("--version", action="version", version=f"diffwitness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    prove = sub.add_parser("prove", help=tr('Build a causal evidence map for a candidate Git diff', 'Construire les preuves causales d’un diff Git candidat'))
    prove.add_argument("--repo", default=".", help=tr('Git repository (default: current directory)', 'Dépôt Git (par défaut : dossier courant)'))
    prove.add_argument("--config", help=tr('Config path (default: .diffwitness.toml when present)', 'Configuration (par défaut : .diffwitness.toml si présent)'))
    prove.add_argument("--base", default="HEAD", help=tr('Base Git ref (default: HEAD)', 'Référence Git de base (par défaut : HEAD)'))
    prove.add_argument(
        "--candidate",
        default="WORKTREE",
        help=tr('Candidate ref, or WORKTREE to snapshot staged/unstaged/untracked changes', 'Référence candidate, ou WORKTREE pour capturer les modifications indexées/non indexées/non suivies'),
    )
    prove.add_argument("--test", help=tr('Evidence command. Can also be set in .diffwitness.toml', 'Commande de vérification, également configurable dans .diffwitness.toml'))
    prove.add_argument("--prepare", help=tr('Setup command run inside each isolated worktree', 'Commande de préparation dans chaque worktree isolé'))
    prove.add_argument("--timeout", type=float, help=tr('Seconds per command', 'Secondes par commande'))
    prove.add_argument(
        "--max-total-seconds",
        type=float,
        help=tr('Maximum wall-clock seconds for the complete proof (default/config: 900)', 'Durée totale maximale de la preuve en secondes (défaut/configuration : 900)'),
    )
    prove.add_argument("--stability-runs", type=int, help=tr('Repeat every evidence variant N times', 'Répéter chaque variante N fois'))
    prove.add_argument("--test-glob", action="append", default=None, help=tr('Additional test-file glob; repeatable', 'Motif de fichiers de test supplémentaire ; répétable'))
    prove.add_argument("--ignore", action="append", default=None, help=tr('Changed path glob to exclude; repeatable', 'Motif de chemins modifiés à exclure ; répétable'))
    prove.add_argument("--include-test-changes", action="store_true", help=tr('Also ablate changed test hunks', 'Retirer aussi les hunks de test modifiés lors de l’analyse'))
    prove.add_argument("--no-test-overlay", action="store_true", help=tr('Do not overlay candidate tests onto base', 'Ne pas superposer les tests candidats sur la base'))
    prove.add_argument("--share", action="append", default=None, metavar="PATH", help=tr('Symlink a repo-relative cache/dependency path into sandboxes', 'Lier un chemin de cache/dépendance du dépôt dans les environnements isolés'))
    prove.add_argument("--minimize", action="store_true", help=tr('Greedily remove production hunks while evidence stays stably green', 'Retirer progressivement les hunks de production tant que les vérifications restent stables et positives'))
    prove.add_argument("--reduction-patch", type=Path, help=tr('Write candidate-to-reduced patch (requires --minimize)', 'Écrire le patch candidat-vers-réduction (nécessite --minimize)'))
    prove.add_argument("--json", dest="json_path", type=Path, help=tr('Write schema-v2 JSON evidence certificate', 'Écrire le certificat JSON canonique schema-v2'))
    prove.add_argument("--certificate", type=Path, help=tr('Alias for --json, emphasizing reusable evidence output', 'Alias de --json pour produire une preuve réutilisable'))
    prove.add_argument("--report", type=Path, help=tr('Write Markdown evidence report', 'Écrire le rapport de preuve canonique Markdown'))
    prove.add_argument("--sufficient-search", action=argparse.BooleanOptionalAction, default=None, help=tr('Search small real-hunk subsets that are sufficient from base', 'Chercher les petits sous-ensembles de hunks suffisants depuis la base'))
    prove.add_argument("--max-subset-order", type=int, help=tr('Maximum cardinality for sufficient-subset search', 'Taille maximale des sous-ensembles suffisants recherchés'))
    prove.add_argument("--max-subset-runs", type=int, help=tr('Maximum subset variants evaluated', 'Nombre maximal de variantes de sous-ensembles évaluées'))
    prove.add_argument("--interaction-search", action=argparse.BooleanOptionalAction, default=None, help=tr('Search unwitnessed hunk pairs for hidden mutual backup', 'Chercher les paires de hunks sans témoin qui se remplacent mutuellement'))
    prove.add_argument("--max-interaction-runs", type=int, help=tr('Maximum pair variants evaluated', 'Nombre maximal de variantes de paires évaluées'))
    prove.add_argument("--github-actions", action=argparse.BooleanOptionalAction, default=None, help=tr('Emit GitHub annotations, outputs and step summary', 'Émettre les annotations, sorties et résumés GitHub canoniques'))
    prove.add_argument("--require-contrast", action="store_true", help=tr('Fail unless base is stably red and candidate stably green', 'Échouer si la base n’échoue pas de façon stable ou si le candidat ne réussit pas de façon stable'))
    prove.add_argument("--require-all-witnessed", action="store_true", help=tr('Fail if any analyzed hunk is unwitnessed or inconclusive', 'Échouer si un hunk analysé est sans témoin ou non concluant'))
    prove.add_argument("--require-no-surplus", action="store_true", help=tr('Fail when exhaustive sufficient search identifies strong surplus candidates', 'Échouer si la recherche exhaustive identifie des candidats fortement superflus'))

    suggest = sub.add_parser("suggest", help=tr('Suggest common test commands without executing them', 'Suggérer des commandes de test courantes sans les exécuter'))
    suggest.add_argument("--repo", default=".")

    init = sub.add_parser("init", help=tr('Create .diffwitness.toml and an optional PR workflow', 'Créer .diffwitness.toml et un workflow PR optionnel'))
    init.add_argument("--repo", default=".")
    init.add_argument("--test", required=True)
    init.add_argument("--prepare")
    init.add_argument("--force", action="store_true")
    init.add_argument("--workflow", action=argparse.BooleanOptionalAction, default=True)

    show = sub.add_parser("show", help="Render a JSON evidence certificate as Markdown")
    show.add_argument("certificate", type=Path)
    return parser


def _suggest(repo: Path) -> list[str]:
    suggestions: list[str] = []
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if "test" in scripts:
                suggestions.append("npm test")
            if "typecheck" in scripts:
                suggestions.append("npm run typecheck")
        except (OSError, json.JSONDecodeError):
            pass
    if (repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists() or (repo / "tests").exists():
        suggestions.append("python -m pytest -q")
    if (repo / "Cargo.toml").exists():
        suggestions.append("cargo test")
    if (repo / "go.mod").exists():
        suggestions.append("go test ./...")
    if (repo / "pom.xml").exists():
        suggestions.append("mvn test")
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        suggestions.append("./gradlew test")
    seen: set[str] = set()
    return [s for s in suggestions if not (s in seen or seen.add(s))]


def _cfg(args: argparse.Namespace, config: dict[str, Any], name: str, default: Any) -> Any:
    value = getattr(args, name)
    if value is not None:
        return value
    return config.get(name, default)


def _list_cfg(args: argparse.Namespace, config: dict[str, Any], arg_name: str, key: str) -> list[str]:
    value = getattr(args, arg_name)
    if value is not None:
        return list(value)
    configured = config.get(key, [])
    return list(configured) if isinstance(configured, list) else []


def _status_line(status: str) -> str:
    return {"witnessed": "WITNESSED   ", "unwitnessed": "UNWITNESSED ", "inconclusive": "INCONCLUSIVE"}[status]


def _write_init_workflow(
    repo: Path,
    *,
    force: bool,
    test_command: str,
    prepare_command: str | None,
) -> Path:
    """Generate a reproducible PR workflow pinned to the installed DiffWitness release.

    The evidence command supplied to `diffwitness init` is embedded explicitly instead of relying
    on a PR-modifiable repository config file. JSON string syntax is valid YAML scalar syntax and
    safely preserves quotes/backslashes in arbitrary shell commands.
    """
    path = repo / ".github" / "workflows" / "diffwitness.yml"
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "name: DiffWitness",
        "",
        "on:",
        "  pull_request:",
        "",
        "permissions:",
        "  contents: read",
        "",
        "jobs:",
        "  evidence:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@v7",
        "        with:",
        "          fetch-depth: 0",
        "      - name: Prove patch evidence",
        f"        uses: TFourniax/tooltest@v{__version__}",
        "        with:",
        "          base: ${{ github.event.pull_request.base.sha }}",
        "          candidate: ${{ github.event.pull_request.head.sha }}",
        f"          test: {json.dumps(test_command, ensure_ascii=False)}",
    ]
    if prepare_command:
        lines.append(f"          prepare: {json.dumps(prepare_command, ensure_ascii=False)}")
    lines += [
        "          policy: balanced",
        "          strategy: auto",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _init(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    config_path = write_config(repo, test=args.test, prepare=args.prepare, force=args.force)
    print(tr(f"created {config_path.relative_to(repo)}", f'créé : {config_path.relative_to(repo)}'))
    if args.workflow:
        workflow = _write_init_workflow(
            repo,
            force=args.force,
            test_command=args.test,
            prepare_command=args.prepare,
        )
        print(tr(f"created {workflow.relative_to(repo)}", f'créé : {workflow.relative_to(repo)}'))
    return 0


def _prove(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    config = load_config(repo, args.config)
    test_command = _cfg(args, config, "test", None)
    if not test_command:
        raise AnalysisError("no evidence command configured; pass --test or create .diffwitness.toml")
    prepare_command = _cfg(args, config, "prepare", None)
    timeout = float(_cfg(args, config, "timeout", 300.0))
    max_total_seconds = float(_cfg(args, config, "max_total_seconds", 900.0))
    stability_runs = int(_cfg(args, config, "stability_runs", 1))
    search_sufficient = bool(_cfg(args, config, "sufficient_search", True))
    max_subset_order = int(_cfg(args, config, "max_subset_order", 3))
    max_subset_runs = int(_cfg(args, config, "max_subset_runs", 32))
    search_interactions = bool(_cfg(args, config, "interaction_search", True))
    max_interaction_runs = int(_cfg(args, config, "max_interaction_runs", 20))
    test_globs = _list_cfg(args, config, "test_glob", "test_glob")
    ignore = _list_cfg(args, config, "ignore", "ignore")
    shared = _list_cfg(args, config, "share", "share")

    if timeout <= 0:
        raise AnalysisError("--timeout must be > 0")
    if max_total_seconds <= 0:
        raise AnalysisError("--max-total-seconds must be > 0")

    base_sha = resolve_analysis_base(repo, args.base)
    if args.candidate.upper() == "WORKTREE":
        candidate_sha = snapshot_worktree(repo)
        candidate_ref = "WORKTREE"
    else:
        candidate_sha = resolve_ref(repo, args.candidate)
        candidate_ref = args.candidate

    raw_diff = diff_text(repo, base_sha, candidate_sha)
    files = parse_file_patches(raw_diff, test_globs=test_globs)
    if not files:
        print(tr("DiffWitness: no changes between base and candidate.", 'DiffWitness : aucune modification entre la base et le candidat.'), file=sys.stderr)
        return 2

    all_mutations = make_mutations(files, include_tests=args.include_test_changes, ignore_globs=[])
    mutations = make_mutations(files, include_tests=args.include_test_changes, ignore_globs=ignore)
    ignored_count = len(all_mutations) - len(mutations)
    if not mutations:
        print(tr("DiffWitness: no analyzable changes remain after test/documentation/ignore filtering.", 'DiffWitness : aucune modification analysable après filtrage tests/documentation/exclusions.'), file=sys.stderr)
        return 2
    if args.reduction_patch and not args.minimize:
        raise AnalysisError("--reduction-patch requires --minimize")

    print(tr(f"DiffWitness {__version__} - counterfactual patch evidence", f'DiffWitness {__version__} - preuves contrefactuelles de la modification'))
    print(tr(f"repo:      {repo}", f'dépôt :    {repo}'))
    print(f"base:      {args.base} ({base_sha[:12]})")
    print(tr(f"candidate: {candidate_ref} ({candidate_sha[:12]})", f'candidat : {candidate_ref} ({candidate_sha[:12]})'))
    print(tr(f"evidence:  {test_command}", f'commande : {test_command}'))
    print(tr(f"stability: {stability_runs} run(s) per variant", f'stabilité : {stability_runs} exécution(s) par variante'))
    print(tr(f"budget:    {max_total_seconds:g}s total; {timeout:g}s per command", f'budget:    {max_total_seconds:g}s au total ; {timeout:g}s par commande'))
    print(tr(f"changes:   {len(mutations)} analyzed mutation(s); {sum(f.is_test for f in files)} changed test file(s)", f'modifications : {len(mutations)} mutation(s) analysée(s) ; {sum((f.is_test for f in files))} fichier(s) de test modifié(s)'))
    print()

    outcome = run_analysis(
        source_repo=repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        files=files,
        mutations=mutations,
        test_command=str(test_command),
        timeout=timeout,
        prepare_command=prepare_command,
        shared_paths=shared,
        overlay_candidate_tests=not args.no_test_overlay,
        minimize=args.minimize,
        stability_runs=stability_runs,
        search_sufficient=search_sufficient,
        max_subset_order=max_subset_order,
        max_subset_runs=max_subset_runs,
        search_interactions=search_interactions,
        max_interaction_runs=max_interaction_runs,
        max_total_seconds=max_total_seconds,
    )

    config_used = {
        "prepare": prepare_command,
        "timeout": timeout,
        "max_total_seconds": max_total_seconds,
        "stability_runs": stability_runs,
        "sufficient_search": search_sufficient,
        "max_subset_order": max_subset_order,
        "max_subset_runs": max_subset_runs,
        "interaction_search": search_interactions,
        "max_interaction_runs": max_interaction_runs,
        "test_glob": test_globs,
        "ignore": ignore,
        "share": shared,
        "test_overlay": not args.no_test_overlay,
    }
    report = build_report(
        repo=repo,
        base_ref=args.base,
        base_sha=base_sha,
        candidate_ref=candidate_ref,
        candidate_sha=candidate_sha,
        test_command=str(test_command),
        outcome=outcome,
        ignored_count=ignored_count,
        config=config_used,
    )

    contrast_label = {
        "base-fail_candidate-pass": "BASE STABLE-FAIL -> CANDIDATE STABLE-PASS",
        "base-pass_candidate-pass": "BASE STABLE-PASS -> CANDIDATE STABLE-PASS (no whole-patch contrast)",
        "base-inconclusive_candidate-pass": "BASE UNSTABLE/TIMEOUT -> CANDIDATE STABLE-PASS (contrast inconclusive)",
        "candidate-not-stable-green": "CANDIDATE NOT STABLY GREEN",
    }[report["contrast"]]
    print(tr(f"contrast:  {contrast_label}", f'contraste : {contrast_label}'))
    print()
    for result in outcome.mutation_results:
        delta = f"+{result.mutation.additions}/-{result.mutation.deletions}"
        stability = result.runs.classification if result.runs else "apply-error"
        print(f"{_status_line(result.status)}  {delta:>9}  {result.mutation.label}  [{stability}]")

    s = report["summary"]
    print()
    print(
        tr(f"summary: {s['witnessed']} witnessed, {s['unwitnessed']} unwitnessed, "
        f"{s['inconclusive']} inconclusive", f"résumé : {s['witnessed']} avec témoin, {s['unwitnessed']} sans témoin, {s['inconclusive']} non concluant(s)")
    )
    if s["minimal_sufficient_order"]:
        print(
            tr(f"core:    {s['minimal_sufficient_sets']} minimal sufficient set(s) of "
            f"{s['minimal_sufficient_order']} hunk(s)", f"core:    {s['minimal_sufficient_sets']} ensemble(s) suffisant(s) minimal(aux) de {s['minimal_sufficient_order']} hunk(s)")
        )
    if s["mutual_backup_pairs"]:
        print(tr(f"backup:  {s['mutual_backup_pairs']} hidden mutual-backup pair(s)", f"backup:  {s['mutual_backup_pairs']} paire(s) de sauvegarde mutuelle cachée(s)"))
    if s["surplus_candidate_hunks"]:
        print(tr(f"surplus: {s['surplus_candidate_hunks']} strong surplus candidate hunk(s)", f"surplus: {s['surplus_candidate_hunks']} hunk(s) candidat(s) fortement superflu(s)"))
    print(f"cert:    {report['certificate_id']}")

    json_path = args.certificate or args.json_path
    if args.certificate and args.json_path and args.certificate != args.json_path:
        raise AnalysisError("use either --certificate or --json, not two different paths")
    if json_path:
        write_json(report, json_path)
    if args.report:
        write_markdown(report, args.report)
    if args.reduction_patch is not None:
        reduction_bytes = supported_patch_bytes(outcome.reduction_patch or "")
        args.reduction_patch.parent.mkdir(parents=True, exist_ok=True)
        args.reduction_patch.write_bytes(reduction_bytes)

    github_mode = is_github_actions() if args.github_actions is None else args.github_actions
    if github_mode:
        emit_annotations(report)
        write_step_summary(report)
        write_outputs(report)

    failed = False
    if args.require_contrast and report["contrast"] != "base-fail_candidate-pass":
        print(tr("DiffWitness gate failed: evidence command does not provide stable base->candidate contrast.", 'Échec de Gate : la commande ne fournit pas de contraste stable base->candidat.'), file=sys.stderr)
        failed = True
    if args.require_all_witnessed and (s["unwitnessed"] or s["inconclusive"]):
        print(tr("DiffWitness gate failed: not every analyzed hunk is causally witnessed.", 'Échec de Gate : tous les hunks analysés ne disposent pas d’un témoin causal.'), file=sys.stderr)
        failed = True
    if args.require_no_surplus and s["surplus_candidate_hunks"]:
        print(tr("DiffWitness gate failed: exhaustive evidence-core search found surplus candidate hunks.", 'Échec de Gate : la recherche exhaustive a trouvé des hunks candidats superflus.'), file=sys.stderr)
        failed = True
    return 1 if failed else 0


def _configure_stdio() -> None:
    """Prefer UTF-8 terminal I/O without ever failing on legacy Windows consoles.

    Reports are already written explicitly as UTF-8, but CLI output can contain
    repository paths, hunk context, or rendered certificate Markdown with Unicode.
    Python may otherwise inherit a legacy Windows code page and raise
    UnicodeEncodeError after the analysis has successfully completed.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = _parser().parse_args(argv)
    try:
        if args.command == "suggest":
            repo = repo_root(args.repo)
            suggestions = _suggest(repo)
            if suggestions:
                print("\n".join(suggestions))
                return 0
            print(tr("No common test command detected.", 'Aucune commande de test courante détectée.'), file=sys.stderr)
            return 1
        if args.command == "init":
            return _init(args)
        if args.command == "show":
            report = json.loads(args.certificate.read_text(encoding="utf-8"))
            print(render_markdown(report))
            return 0
        if args.command == "prove":
            return _prove(args)
    except (GitError, AnalysisError, ValueError, FileExistsError, OSError) as exc:
        print(f"DiffWitness: {exc}", file=sys.stderr)
        return 2
    return 2
