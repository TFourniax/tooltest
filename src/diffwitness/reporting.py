from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CommandResult, MutationResult


def build_report(
    *,
    repo: Path,
    base_ref: str,
    base_sha: str,
    candidate_ref: str,
    candidate_sha: str,
    test_command: str,
    candidate_result: CommandResult,
    baseline_result: CommandResult,
    results: list[MutationResult],
    test_files: list[str],
    ignored_count: int,
    minimized_removed: list[str] | None = None,
) -> dict[str, Any]:
    witnessed = sum(r.status == "witnessed" for r in results)
    unwitnessed = sum(r.status == "unwitnessed" for r in results)
    inconclusive = sum(r.status == "inconclusive" for r in results)
    contrast = "base-fail_candidate-pass" if (not baseline_result.passed and candidate_result.passed) else (
        "base-pass_candidate-pass" if baseline_result.passed and candidate_result.passed else "candidate-not-green"
    )
    return {
        "schema_version": 1,
        "tool": "diffwitness",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "base": {"ref": base_ref, "sha": base_sha},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha},
        "test_command": test_command,
        "contrast": contrast,
        "candidate_run": candidate_result.to_dict(),
        "baseline_with_candidate_tests_run": baseline_result.to_dict(),
        "candidate_test_files_overlaid_on_base": sorted(test_files),
        "summary": {
            "mutations": len(results),
            "witnessed": witnessed,
            "unwitnessed": unwitnessed,
            "inconclusive": inconclusive,
            "ignored": ignored_count,
            "witness_ratio": (witnessed / (witnessed + unwitnessed)) if (witnessed + unwitnessed) else None,
        },
        "minimization": {
            "removed_mutation_ids": minimized_removed or [],
            "note": "Greedy/local minimum; another removal order may produce a different passing subset.",
        } if minimized_removed is not None else None,
        "results": [r.to_dict() for r in results],
        "interpretation": {
            "witnessed": "Removing this candidate change made the selected test command fail.",
            "unwitnessed": "The selected test command still passed without this change; it does not currently witness thhÈ[šÉÜÈ™XÙ\ÜÚ]Kˆ‹ˆš[˜ÛÛ˜Û\Ú]™Hˆ‘Y™•Ú]™\ÜÈÛİ[›İ›ÙXÙHH™[XX›HÛİ[\™˜XİX[™\İ[›Üˆ\ÈÚ[™ÙKˆ‹ˆKˆ˜Ø]™X]ˆ“™XÙ\ÜÚ]H[™\ˆÛ™HÙ[XİY\İÛÛ[X[™\È›İÛÜœ™Xİ™\ÜÈ›ÛÙ‹ˆHÚ]™\ÜÙY[šÈØ[ˆ™H™XÙ\ÜØ\HÛ›H™XØ]\ÙHÙˆZ[Üˆ[\˜Xİ[Ûˆ\[™[˜ÚY\ÎÈ[ˆ[Ú]™\ÜÙY[šÈØ[ˆİ[™H˜[Y™Z]š[Üˆ›İ^\˜Ú\ÙYH\ÈÛÛ[X[™ˆ‹ˆB‚‚™YˆÜš]WÚœÛÛŠ™\ÜˆXİÜİ‹[WK]ˆ]
HOˆ›Û™N‚ˆ]œ\™[›ZÙ\Š\™[ÏUYK^\İÛÚÏUYJBˆ]Üš]Wİ^
œÛÛ‹™[\Ê™\Ü[™[L‹[œİ\™WØ\ØÚZOQ˜[ÙJH
È—ˆ‹[˜ÛÙ[™ÏH]‹NŠB‚‚™Yˆ×ÛX\šÙİÛŠ™\ÜˆXİÜİ‹[WJHOˆİ‚ˆÈH™\ÜÈœİ[[X\H—BˆÛÛ˜\İH™\ÜÈ˜ÛÛ˜\İ—Bˆ[™\ÈHÂˆˆÈY™•Ú]™\ÜÈ™\Ü‹ˆˆ‹ˆˆ‹H
Š˜\ÙNŠŠˆÜ™\ÜÉØ˜\ÙI×VÉÜ™Y‰×_X
Ü™\ÜÉØ˜\ÙI×VÉÜÚI×VÎŒL—_X
H‹ˆˆ‹H
ŠØ[™Y]NŠŠˆÜ™\ÜÉØØ[™Y]I×VÉÜ™Y‰×_X
Ü™\ÜÉØØ[™Y]I×VÉÜÚI×VÎŒL—_X
H‹ˆˆ‹H
Š•\İÛÛ[X[™ŠŠˆÜ™\ÜÉİ\İØÛÛ[X[™	×_X‹ˆˆ‹H
ŠÛÛ˜\İŠŠˆØÛÛ˜\İX‹ˆˆ‹H
Š•Ú]™\ÜÙYŠŠˆÜÖÉİÚ]™\ÜÙY	×_HÈÜÖÉİÚ]™\ÜÙY	×H
ÈÖÉİ[Ú]™\ÜÙY	×_HÛÛ˜Û\Ú]™H]]][ÛœÈ‹ˆˆ‹ˆŸİ]\ÈÚ[™ÙH3¥YX[š[™È‹ˆŸKK_KK_KKNŸKK_‹ˆBˆYX[š[™ÜÈHÂˆÚ]™\ÜÙYˆ”™[[İš[™È]XYH\İÈ˜Z[‹ˆ[Ú]™\ÜÙYˆ•\İÈİ^YYÜ™Y[ˆÚ]İ]]‹ˆš[˜ÛÛ˜Û\Ú]™HˆÛİ[›İ]˜[X]H™[XX›H‹ˆBˆXÛÛœÈHÈÚ]™\ÜÙYˆ•ÒU‘TÔÑQ‹[Ú]™\ÜÙYˆ•S•ÒU‘TÔÑQ‹š[˜ÛÛ˜Û\Ú]™Hˆ’SÓÓÓTÒU‘HŸBˆ›Üˆ][H[ˆ™\ÜÈœ™\İ[È—N‚ˆ]]][ÛˆH][VÈ›]]][Ûˆ—BˆX™[H]]][Û–È›X™[—Kœ™\XÙJŸ‹—ŠBˆ[HHˆŠŞÛ]]][Û–ÉØY][ÛœÉ×_KË^Û]]][Û–ÉÙ[][ÛœÉ×_H‚ˆİ]\ÈH][VÈœİ]\È—Bˆ[™\Ë˜\[™
ˆŸÚXÛÛœÖÜİ]\×_HÛX™[XÙ[_HÛYX[š[™ÜÖÜİ]\×_HŠBˆYˆ™\Ü™Ù]
˜Ø[™Y]Wİ\İÙš[\×Ûİ™\›ZYÛÛ—Ø˜\ÙHŠN‚ˆ[™\È
ÏHÈˆ‹ˆÈÈ\İİ™\›^H‹ˆ‹Ø[™Y]K\ÚYH\İÚ[™Ù\ÈÙ\™Hİ™\›ZYÛÈH˜\ÙH™Y›Ü™HH˜\Ù[[™H[ˆ—Bˆ[™\È
ÏHÙˆ‹HÜ]Xˆ›Üˆ][ˆ™\ÜÈ˜Ø[™Y]Wİ\İÙš[\×Ûİ™\›ZYÛÛ—Ø˜\ÙH—WBˆYˆ™\Ü™Ù]
›Z[š[Z^˜][ÛˆŠH\È›İ›Û™N‚ˆ™[[İ™YH™\ÜÈ›Z[š[Z^˜][Ûˆ—VÈœ™[[İ™YÛ]]][Û—ÚYÈ—Bˆ[™\È
ÏHÈˆ‹ˆÈÈÜ™YYHZ[š[Z^˜][Ûˆ‹ˆ‹ˆ”™[[İ˜X›HÚ[HHÙ[XİY\İÛÛ[X[™İ^YYÜ™Y[ˆ
ŠÛ[Š™[[İ™Y
_JŠˆ]]][ÛŠÊKˆ—BˆYˆ™[[İ™Y‚ˆ[™\Ë˜\[™
ˆŠBˆ[™\È
ÏHÙˆ‹HÛZYXˆ›ÜˆZY[ˆ™[[İ™YBˆ[™\È
ÏHÂˆˆ‹ˆˆÈÈ[\Ü[[Z]][Ûˆ‹ˆˆ‹ˆ™\ÜÈ˜Ø]™X]—Kˆˆ‹ˆBˆ™]\›ˆ—ˆ‹š›Ú[Š[™\ÊB‚‚™YˆÜš]WÛX\šÙİÛŠ™\ÜˆXİÜİ‹[WK]ˆ]
HOˆ›Û™N‚ˆ]œ\™[›ZÙ\Š\™[ÏUYK^\İÛÚÏUYJBˆ]Üš]Wİ^
×ÛX\šÙİÛŠ™\Ü
K[˜ÛÙ[™ÏH]‹NŠB