from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analysis import AnalysisError, run_analysis
from .diffing import make_mutations, parse_file_patches
from .gitops import GitError, diff_text, repo_root, resolve_ref, snapshot_worktree
from .reporting import build_report, write_json, write_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffwitness",
        description="Counterfactual test evidence for Git diffs: find which patch hunks your tests actually witness.",
    )
    parser.add_argument("--version", action="version", version=f"diffwitness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    prove = sub.add_parser("prove", help="Replay tests against base, candidate, and candidate-minus-each-change")
    prove.add_argument("--repo", default=".", help="Git repository (default: current directory)")
    prove.add_argument("--base", default="HEAD", help="Base Git ref (default: HEAD)")
    prove.add_argument(
        "--candidate",
        default="WORKTREE",
        help="Candidate Git ref, or WORKTREE to snapshot staged/unstaged/untracked changes (default: WORKTREE)",
    )
    prove.add_argument("--test", required=True, help="Test command to execute in disposable Git worktrees")
    prove.add_argument("--prepare", help="Optional setup command run once in each isolated base/candidate worktree")
    prove.add_argument("--timeout", type=float, default=300.0, help="Seconds per command (default: 300)")
    prove.add_argument("--test-glob", action="append", default=[], help="Additional glob classied as test code; repeatable")
    prove.add_argument("--ignore", action="append", default=[], help="Changed path glob to exclude from hunk witness analysis; repeatable")
    prove.add_argument("--include-test-changes", action="store_true", help="Also mutate test-file hunks (off by default)")
    prove.add_argument("--no-test-overlay", action="store_true", help="Do not overlay candidate test changes onto the base run")
    prove.add_argument(
        "--share",
        action="append",
        default=[],
        metavar ="PATH",
        help="Symlink a repo-relative dependency/cache path into sandboxes (e.g. node_modules); repeatable. Tests can mutate the shared target.",
    )
    prove.add_argument("--minimize", action="store_true", help="Greedily find a smaller candidate diff that still passes the selected tests")
    prove.add_argument("--reduction-patch", type=Path, help="Write candidateâ†’reduced patch (requires --minimize)")
    prove.add_argument("--json", dest="json_path", type=Path, help="Write machine-readable JSON report")
    prove.add_argument("--report", type=Path, help="Write Markdown report")
    prove.add_argument("--require-contrast", action="store_true", help="Exit non-zero unless base+candidate-tests fails and candidate passes")
    prove.add_argument("--require-all-witnessed", action="store_true", help="Exit non-zero if any conclusive production mutation is unwitnessed")

    suggest = sub.add_parser("suggest", help="Suggest common test commands from repository files without executing them")
    suggest.add_argument("--repo", default=".")
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


def _status_line(status: str) -> str:
    return {
        "witnessed": "WITNESSED   ",
        "unwitnessed": "UNWITNESSED  ",
        "inconclusive": "INCONCLUSIVE",
    }[status]


def _prove(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    base_sha = resolve_ref(repo, args.base)
    if args.candidate.upper() == "WORKTREE":
        candidate_sha = snapshot_worktree(repo)
        candidate_ref = "WORKTREE"
    else:
        candidate_sha = resolve_ref(repo, args.candidate)
        candidate_ref = args.candidate

    raw_diff = diff_text(repo, base_sha, candidate_sha)
    files = parse_file_patches(raw_diff, test_globs=args.test_glob)
    if not files:
        print("DiffWitness: no changes between base and candidate.", file=sys.stderr)
        return 2

    all_mutations = make_mutations(files, include_tests=args.include_test_changes, ignore_globs=[])
    mutations = make_mutations(files, include_tests=args.include_test_changes, ignore_globs=args.ignore)
    ignored_count = len(all_mutations) - len(mutations)
    if not mutations:
        print("DiffWitness: no analyzable changes remain after test/ignore filtering.", file=sys.stderr)
        return 2

    if args.reduction_patch and not args.minimize:
        print("DiffWitness: --reduction-patch requires --minimize.", file=sys.stderr)
        return 2

    print("DiffWitness â€” counterfactual patch evidence")
    print(f"repo:      {repo}")
    print(f"base:      {args.base} ({base_sha[:12]})")
    print(f"candidate: {candidate_ref} ({candidate_sha[:12]})")
    print(f"test:      {args.test}")
    print(f"changes:   {len(mutations)} production mutation(s); {sum(f.is_test for f in files)} changed test file(s)")
    print()

    candidate_result, baseline_result, results, test_files, minimized_removed, reduction_patch = run_analysis(
        source_repo=repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        files=files,
        mutations=mutations,
        test_command=args.test,
        timeout=args.timeout,
        prepare_command=args.prepare,
        shared_paths=args.share,
        overlay_candidate_tests=not args.no_test_overlay,
        minimize=args.minimize,
    )

    contrast = not baseline_result.passed and candidate_result.passed
    if contrast:
        print("contrast:  BASE FAIL â†’ CANDIDATE PASS  [bug-discriminating command]")
    else:
        print("contrast:  BASE PASS â†’ CANDIDATE PASS  [command does not distinguish the whole patch from base]")
    print()
    for result in results:
        delta = f"+{result.mutation.additions}/-{resu[›]]][Û‹™[][ÛœßH‚ˆš[
ˆ×Üİ]\×Û[™J™\İ[œİ]\Ê_HÜ™\İ[›]]][Û‹šYHÙ[N_HÜ™\İ[›]]][Û‹›X™[HŠBˆYˆ™\İ[œİ]\ÈOHš[˜ÛÛ˜Û\Ú]™Hˆ[™™\İ[˜\WÙ\œ›Ü‚ˆš[
ˆˆ\NˆÜ™\İ[˜\WÙ\œ›Ü‹œÜ][™\Ê
VËLWVÎŒMŒ_HŠB‚ˆÚ]™\ÜÙYHİ[J‹œİ]\ÈOHÚ]™\ÜÙYˆ›Üˆˆ[ˆ™\İ[ÊBˆ[Ú]™\ÜÙYHİ[J‹œİ]\ÈOH[Ú]™\ÜÙYˆ›Üˆˆ[ˆ™\İ[ÊBˆÛÛ˜Û\Ú]™HHÚ]™\ÜÙY
È[Ú]™\ÜÙYˆš[

BˆYˆÛÛ˜Û\Ú]™N‚ˆš[
ˆÚ]™\ÜÈX\ˆİÚ]™\ÜÙYKŞØÛÛ˜Û\Ú]™_HÛÛ˜Û\Ú]™HÚ[™Ù\È\™H™XÙ\ÜØ\H›Üˆ\È\İÛÛ[X[™Èİ^HÜ™Y[ˆŠBˆ[ÙN‚ˆš[
Ú]™\ÜÈX\ˆ›ÈÛÛ˜Û\Ú]™H]]][ÛœÈŠBˆYˆ\™ÜË›Z[š[Z^™H[™™YXİ[Û—Ü]Ú\È›İ›Û™N‚ˆÈQÈ\™H™XÛÛ\]Y™[İÈœ›ÛH™\İ[È]™XØ[YH™[[İ˜X›H[ˆ™\Ü	ÜÈZ[š[Z^˜][Ûˆ]‚ˆš[
›Z[š[Z^™NˆÛÛ\]YÜ™YYKÛØØ[™YXİ[ÛˆÙX\˜ÚŠB‚ˆ™\ÜHZ[Ü™\Ü
ˆ™\Ï\™\Ëˆ˜\ÙWÜ™YX\™ÜË˜˜\ÙKˆ˜\ÙWÜÚOX˜\ÙWÜÚKˆØ[™Y]WÜ™YXØ[™Y]WÜ™Y‹ˆØ[™Y]WÜÚOXØ[™Y]WÜÚKˆ\İØÛÛ[X[™X\™ÜË\İˆØ[™Y]WÜ™\İ[XØ[™Y]WÜ™\İ[ˆ˜\Ù[[™WÜ™\İ[X˜\Ù[[™WÜ™\İ[ˆ™\İ[Ï\™\İ[Ëˆ\İÙš[\Ï]\İÙš[\ËˆYÛ›Ü™YØÛİ[ZYÛ›Ü™YØÛİ[ˆZ[š[Z^™YÜ™[[İ™Y[Z[š[Z^™YÜ™[[İ™Yˆ
BˆYˆ\™ÜËšœÛÛ—Ü]‚ˆÜš]WÚœÛÛŠ™\Ü\™ÜËšœÛÛ—Ü]
Bˆš[
ˆšœÛÛˆØ\™ÜËšœÛÛ—Ü]HŠBˆYˆ\™ÜËœ™\Ü‚ˆÜš]WÛX\šÙİÛŠ™\Ü\™ÜËœ™\Ü
Bˆš[
ˆœ™\ÜˆØ\™ÜËœ™\ÜHŠBˆYˆ\™ÜËœ™YXİ[Û—Ü]Ú\È›İ›Û™N‚ˆ\™ÜËœ™YXİ[Û—Ü]Úœ\™[›ZÙ\Š\™[ÏUYK^\İÛÚÏUYJBˆ\™ÜËœ™YXİ[Û—Ü]ÚÜš]Wİ^
™YXİ[Û—Ü]ÚÜˆˆ‹[˜ÛÙ[™ÏH]‹NŠBˆš[
ˆœ™YXİ[ÛˆØ\™ÜËœ™YXİ[Û—Ü]ÚHŠB‚ˆš[

BˆYˆ[Ú]™\ÜÙY‚ˆš[
’[\œ™]][ÛˆS•ÒU‘TÔÑQHÙ\È›İYX[ˆ	İÜ›Û™ÉËˆ]YX[œÈHÙ[XİY\İÛÛ[X[™İ^\ÈÜ™Y[ˆÚ]İ]]Ú[™ÙH8 %ÛÈ]Ú[™ÙHİ\œ™[H\È›ÈÛİ[\™˜XİX[Ú]™\ÜÈ\™KˆŠBˆYˆ\İÙš[\È[™›İ\™ÜË››×İ\İÛİ™\›^N‚ˆš[
ˆ˜\Ù[[™H˜Z\›™\ÜÎˆİ™\›ZYÛ[Š\İÙš[\Ê_HØ[™Y]K\ÚYH\İš[HÚ[™ÙJÊHÛÈH˜\ÙH™Y›Ü™H™\^KˆŠB‚ˆYˆ\™ÜËœ™\]Z\™WØÛÛ˜\İ[™›İÛÛ˜\İ‚ˆ™]\›ˆÂˆYˆ\™ÜËœ™\]Z\™WØ[İÚ]™\ÜÙY[™[Ú]™\ÜÙY‚ˆ™]\›ˆˆ™]\›ˆ‚‚™YˆXZ[Š\™İˆ\İÜİ—H›Û™HH›Û™JHOˆ[‚ˆ\œÙ\ˆHÜ\œÙ\Š
Bˆ\™ÜÈH\œÙ\‹œ\œÙWØ\™ÜÊ\™İŠBˆN‚ˆYˆ\™ÜË˜ÛÛ[X[™OHœİYÙÙ\İ‚ˆ™\ÈH™\×Ü›Ûİ
\™ÜËœ™\ÊBˆİYÙÙ\İ[ÛœÈHÜİYÙÙ\İ
™\ÊBˆYˆİYÙÙ\İ[ÛœÎ‚ˆš[
”İYÙÙ\İYÛÛ[X[™È
›İ^Xİ]Y
NˆŠBˆ›ÜˆİYÙÙ\İ[Ûˆ[ˆİYÙÙ\İ[ÛœÎ‚ˆš[
ˆˆÜİYÙÙ\İ[ÛŸHŠBˆ[ÙN‚ˆš[
“›ÈÛÛ[[Ûˆ\İÛÛ[X[™]XİYˆ\ÜÈ[ˆ^XÚ]ÛÛ[X[™ÈY™Ú]™\ÜÈ›İ™HK]\İ‹‹˜ˆŠBˆ™]\›ˆˆYˆ\™ÜË˜ÛÛ[X[™OHœ›İ™H‚ˆ™]\›ˆÜ›İ™J\™ÜÊBˆ\œÙ\‹™\œ›ÜŠ[šÛ›İÛˆÛÛ[X[™ŠBˆ^Ù\
Ú]\œ›Ü‹[˜[\Ú\Ñ\œ›ÜŠH\È^Î‚ˆš[
ˆ‘Y™•Ú]™\ÜÈ\œ›ÜˆÙ^ßH‹š[O\Ş\Ëœİ\œŠBˆ™]\›ˆ‚ˆ™]\›ˆ‚‚‚šYˆ×Û˜[YW×ÈOH—×ÛXZ[—×È‚ˆ˜Z\ÙHŞ\İ[Q^]
XZ[Š
JB