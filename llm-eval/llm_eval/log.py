"""
Flat file logger for LLM evaluation runs.

Writes a single chronological log file per run with timestamps,
timing, tokens, full LLM responses, and a summary with comparisons.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .types import GenerationResult, HeadToHeadResult, IndividualScore

_log_path: Path | None = None


def init_log(run_dir: Path, pack_name: str) -> Path:
    """Initialize the log file for a run. Returns the log path."""
    global _log_path
    _log_path = run_dir / "run.log"
    _write(f"{'=' * 80}")
    _write(f"LLM-EVAL RUN LOG")
    _write(f"Pack: {pack_name}")
    _write(f"Started: {datetime.now().isoformat()}")
    _write(f"{'=' * 80}\n")
    return _log_path


def log_generation(result: GenerationResult) -> None:
    """Log a single generation result with full response data."""
    _write(f"--- GENERATION {_ts()} ---")
    _write(f"Provider: {result.name} ({result.provider})")
    _write(f"Model:    {result.model}")
    _write(f"Prompt:   {result.prompt_key} — {result.prompt_label}")
    _write(f"Time:     {result.elapsed_s}s")
    _write(f"Tokens:   {result.input_tokens or '?'} in / {result.output_tokens or '?'} out")
    if result.error:
        _write(f"ERROR:    {result.error}")
    else:
        _write(f"Response ({len(result.content)} chars):")
        _write(result.content)
    _write("")


def log_score(score: IndividualScore) -> None:
    """Log an individual scoring result."""
    _write(f"--- SCORE {_ts()} ---")
    _write(f"Provider: {score.name} ({score.provider})")
    _write(f"Prompt:   {score.prompt_key}")
    _write(f"Weighted: {score.weighted_total:.2f}/5.00")
    for key, data in score.scores.items():
        if isinstance(data, dict) and "score" in data:
            _write(f"  {key}: {data['score']}/5")
    if score.auto_scores:
        _write(f"Auto-scores:")
        for key, data in score.auto_scores.items():
            _write(f"  {key}: {data.get('score', '?')}/5 — {data.get('details', '')}")
    _write("")


def log_head_to_head(h2h: HeadToHeadResult) -> None:
    """Log a head-to-head comparison result."""
    _write(f"--- HEAD-TO-HEAD {_ts()} ---")
    _write(f"Prompt:      {h2h.prompt_key}")
    _write(f"Matchup:     {h2h.provider_a} vs {h2h.provider_b}")
    _write(f"Round 1:     {h2h.round_1_winner}")
    _write(f"Round 2:     {h2h.round_2_winner}")
    _write(f"Winner:      {h2h.final_winner} ({h2h.consistency})")
    _write(f"Reasoning:   {h2h.reasoning}")
    _write("")


def log_summary(
    scores: list[IndividualScore],
    head_to_head: list[HeadToHeadResult] | None = None,
) -> None:
    """Log a summary with aggregate rankings and comparison tallies."""
    _write(f"\n{'=' * 80}")
    _write(f"SUMMARY — {_ts()}")
    _write(f"{'=' * 80}\n")

    # Aggregate scores per provider
    agg: dict[str, dict] = {}
    for s in scores:
        p = s.provider
        if p not in agg:
            agg[p] = {"name": s.name or p, "totals": [], "times": [], "tokens": []}
        agg[p]["totals"].append(s.weighted_total)
        if s.elapsed_s:
            agg[p]["times"].append(s.elapsed_s)
        if s.output_tokens:
            agg[p]["tokens"].append(s.output_tokens)

    ranked = []
    for p, data in agg.items():
        avg_score = sum(data["totals"]) / len(data["totals"])
        avg_time = sum(data["times"]) / len(data["times"]) if data["times"] else 0
        total_tokens = sum(data["tokens"])
        ranked.append((data["name"], p, avg_score, avg_time, total_tokens, len(data["totals"])))

    ranked.sort(key=lambda x: x[2], reverse=True)

    _write("RANKINGS:")
    _write(f"{'Rank':<6} {'Provider':<30} {'Avg Score':<12} {'Avg Time':<12} {'Total Tokens':<14} {'Prompts'}")
    _write("-" * 80)
    for i, (name, key, avg, avg_t, tot_tok, count) in enumerate(ranked, 1):
        _write(f"{i:<6} {name:<30} {avg:.2f}/5.00    {avg_t:.1f}s         {tot_tok:<14} {count}")

    # Head-to-head tally
    if head_to_head:
        _write(f"\nHEAD-TO-HEAD WIN TALLY:")
        wins: dict[str, int] = {}
        ties = 0
        for h in head_to_head:
            if h.final_winner == "tie":
                ties += 1
            else:
                wins[h.final_winner] = wins.get(h.final_winner, 0) + 1

        for p, count in sorted(wins.items(), key=lambda x: x[1], reverse=True):
            _write(f"  {p}: {count} wins")
        if ties:
            _write(f"  ties: {ties}")

    _write(f"\nCompleted: {datetime.now().isoformat()}")
    _write(f"{'=' * 80}")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(text: str) -> None:
    if _log_path:
        with open(_log_path, "a") as f:
            f.write(text + "\n")
