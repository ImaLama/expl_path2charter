"""
Report generator — produces markdown comparison reports and JSON score files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .providers import get_all_providers
from .types import ChallengePack, HeadToHeadResult, IndividualScore


def generate_report(
    scores: list[IndividualScore],
    head_to_head: list[HeadToHeadResult] | None,
    pack: ChallengePack,
    judge_provider: str,
    output_dir: Path,
) -> Path:
    """Generate a markdown comparison report. Returns path to the report."""
    providers = get_all_providers()
    judge_name = providers.get(judge_provider, None)
    judge_display = judge_name.name if judge_name else judge_provider
    rubric = pack.get_rubric()

    lines: list[str] = [
        f"# {pack.name} — Model Comparison Report",
        f"\n**Judge model:** {judge_display}  ",
        f"**Pack:** {pack.name} — {pack.description}  ",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}  ",
        "",
    ]

    # ── Per-prompt score tables ──
    if scores:
        lines.append("## Individual Scores\n")

        by_prompt: dict[str, list[IndividualScore]] = {}
        for s in scores:
            by_prompt.setdefault(s.prompt_key, []).append(s)

        for prompt_key, prompt_scores in by_prompt.items():
            lines.append(f"### {prompt_key}\n")

            # Build header from rubric criteria
            header_parts = ["| Provider"]
            for c in rubric.criteria:
                header_parts.append(f" {c.label}")
            header_parts.extend([" **Weighted**", " Time", " Tokens |"])
            lines.append(" |".join(header_parts))

            sep_parts = ["|---"] * (len(rubric.criteria) + 4)
            lines.append("|".join(sep_parts) + "|")

            prompt_scores.sort(key=lambda x: x.weighted_total, reverse=True)
            for s in prompt_scores:
                row = [f"| {s.name or s.provider}"]
                for c in rubric.criteria:
                    score_val = s.scores.get(c.key, {}).get("score", "?")
                    row.append(f" {score_val}")
                row.append(f" **{s.weighted_total:.2f}**")
                row.append(f" {s.elapsed_s or '?'}s")
                row.append(f" {s.output_tokens or '?'} |")
                lines.append(" |".join(row))

            # Flagged issues
            for s in prompt_scores:
                notes = s.scores.get("overall_notes", "")
                if notes:
                    lines.append(f"\n> **{s.name or s.provider}:** {notes}")

                # Check for fabricated content (domain packs may include this)
                fab = s.scores.get("fabricated_content", [])
                if fab:
                    lines.append(
                        f"\n> WARNING: **{s.name or s.provider}** — "
                        f"Fabricated content: {', '.join(fab)}"
                    )

            # Auto-scores section
            auto_scores_present = any(s.auto_scores for s in prompt_scores)
            if auto_scores_present:
                lines.append(f"\n#### Auto-Scores\n")
                for s in prompt_scores:
                    if s.auto_scores:
                        lines.append(f"**{s.name or s.provider}:**")
                        for crit_key, crit_data in s.auto_scores.items():
                            score_val = crit_data.get("score", "?")
                            details = crit_data.get("details", "")
                            lines.append(f"  - {crit_key}: {score_val}/5 — {details}")

            lines.append("")

        # ── Aggregate rankings ──
        lines.append("## Aggregate Rankings (across all prompts)\n")
        agg: dict[str, dict] = {}
        for s in scores:
            p = s.provider
            if p not in agg:
                agg[p] = {"name": s.name or p, "totals": [], "times": []}
            agg[p]["totals"].append(s.weighted_total)
            if s.elapsed_s:
                agg[p]["times"].append(s.elapsed_s)

        ranked = []
        for p, data in agg.items():
            avg = sum(data["totals"]) / len(data["totals"])
            avg_time = sum(data["times"]) / len(data["times"]) if data["times"] else 0
            ranked.append((data["name"], avg, avg_time, len(data["totals"])))

        ranked.sort(key=lambda x: x[1], reverse=True)
        lines.append("| Rank | Provider | Avg Score | Avg Time | Prompts Tested |")
        lines.append("|---|---|---|---|---|")
        for i, (name, avg, avg_time, count) in enumerate(ranked, 1):
            lines.append(
                f"| {i} | {name} | **{avg:.2f}**/5.00 | {avg_time:.1f}s | {count} |"
            )
        lines.append("")

    # ── Head-to-head results ──
    if head_to_head:
        lines.append("## Head-to-Head Comparisons\n")

        for h in head_to_head:
            lines.append(
                f"- **{h.provider_a}** vs **{h.provider_b}** "
                f"({h.prompt_key}): winner = **{h.final_winner}** "
                f"[{h.consistency}]"
            )
            if h.reasoning:
                lines.append(f"  > {h.reasoning}")

        # Win tally
        lines.append("\n### Win Tally\n")
        wins: dict[str, int] = {}
        for h in head_to_head:
            if h.final_winner != "tie":
                wins[h.final_winner] = wins.get(h.final_winner, 0) + 1

        if wins:
            lines.append("| Provider | Wins |")
            lines.append("|---|---|")
            for p, count in sorted(wins.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| {p} | {count} |")
        else:
            lines.append("All comparisons resulted in ties.")
        lines.append("")

    # Write report
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"{ts}_scores_{judge_provider}.md"
    report = "\n".join(lines)
    report_path.write_text(report)
    print(f"\nReport saved to {report_path}")

    # Save scores JSON
    scores_json_path = output_dir / f"{ts}_scores_{judge_provider}.json"
    scores_data = {
        "judge": judge_provider,
        "pack": pack.name,
        "individual_scores": [_score_to_dict(s) for s in scores],
        "head_to_head": [_h2h_to_dict(h) for h in head_to_head] if head_to_head else [],
    }
    scores_json_path.write_text(json.dumps(scores_data, indent=2, default=str))
    print(f"Scores JSON saved to {scores_json_path}")

    return report_path


def _score_to_dict(s: IndividualScore) -> dict:
    return {
        "provider": s.provider,
        "model": s.model,
        "name": s.name,
        "prompt_key": s.prompt_key,
        "scores": s.scores,
        "weighted_total": s.weighted_total,
        "auto_scores": s.auto_scores,
        "elapsed_s": s.elapsed_s,
        "output_tokens": s.output_tokens,
    }


def _h2h_to_dict(h: HeadToHeadResult) -> dict:
    return {
        "prompt_key": h.prompt_key,
        "provider_a": h.provider_a,
        "provider_b": h.provider_b,
        "round_1_winner": h.round_1_winner,
        "round_2_winner": h.round_2_winner,
        "final_winner": h.final_winner,
        "consistency": h.consistency,
        "reasoning": h.reasoning,
    }
