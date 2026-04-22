#!/usr/bin/env python3
"""
LLM-as-Judge Scorer for PF2e Character Builds

Takes the results JSON from test_chargen.py, sends each character build to a
judge model (blind — no provider identity), and collects structured scores.

Uses a single strong judge model to avoid self-preference bias. Runs each
judgment twice with reversed presentation order to detect positional bias.

Usage:
    python score_chargen.py results/20250318_143000_results.json
    python score_chargen.py results/20250318_143000_results.json --judge gemini
    python score_chargen.py results/20250318_143000_results.json --judge anthropic --head-to-head
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Judge model configs
# ---------------------------------------------------------------------------
JUDGES = {
    "gemini": {
        "name": "Gemini 2.5 Pro (judge)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GEMINI_API_KEY",
        "model": "gemini-2.5-pro",
    },
    "anthropic": {
        "name": "Claude Opus 4.6 (judge)",
        "env_key": "ANTHROPIC_API_KEY",
        "model": "claude-opus-4-6",
        "native_sdk": True,
    },
    "openai": {
        "name": "GPT-5.2 (judge)",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "model": "gpt-5.2",
    },
    "deepseek": {
        "name": "DeepSeek V3.2 (judge)",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "ollama": {
        "name": "Local model (judge)",
        "model": "qwen2.5:32b-instruct-q5_K_M",
    },
}

# ---------------------------------------------------------------------------
# Scoring rubric — sent to the judge model
# ---------------------------------------------------------------------------
INDIVIDUAL_SCORE_PROMPT = """\
You are an expert Pathfinder 2nd Edition rules judge. You will evaluate a character \
build for mechanical accuracy and quality.

## The original prompt given to the builder:
<prompt>
{prompt}
</prompt>

## The character build to evaluate:
<character_build>
{build}
</character_build>

## Scoring rubric — score each criterion from 1 (terrible) to 5 (flawless):

### 1. Rule Legality (weight: 30%)
Does the build follow PF2e rules correctly? Check for:
- Valid ancestry/heritage/background combinations
- Correct ability score math (boosts/flaws applied properly)
- Feats that actually exist in PF2e and are taken at legal levels
- Class features applied correctly for the level
- Proficiency progressions that match the class
- Multiclass/archetype rules followed (if applicable)
Score 1 = multiple fabricated rules/feats. Score 5 = every detail is rules-legal.

### 2. Completeness (weight: 20%)
Are all required character elements filled in?
- Ability scores, HP, AC, saves, perception
- All feat slots filled (ancestry, class, general, skill — at correct levels)
- Skills with proficiency ranks
- Equipment with costs
- Spells if applicable (correct slots, valid spell list)
Score 1 = major sections missing. Score 5 = every slot filled, nothing left blank.

### 3. Concept Fidelity (weight: 20%)
Does the build match what the user asked for?
- Ancestry/class/theme matches the request
- Mechanical choices support the stated concept
- If the prompt was vague, did the builder make a coherent interpretation?
Score 1 = ignores the request. Score 5 = nails the concept perfectly.

### 4. Mechanical Cohesion (weight: 15%)
Do the choices synergize into an effective character?
- Ability scores support the class/build
- Feats complement each other and the playstyle
- Equipment choices make sense for the build
- The character would actually function well in play
Score 1 = random/contradictory choices. Score 5 = tight, optimized synergy.

### 5. Creativity & Presentation (weight: 15%)
Is the build interesting and well-presented?
- Are choices beyond the most obvious/generic defaults?
- Is the backstory/personality meaningful (not boilerplate)?
- Is the formatting clear and easy to follow?
- Does it show genuine PF2e system knowledge?
Score 1 = bland/cookie-cutter. Score 5 = inspired and expertly presented.

## Response format
Respond with ONLY a JSON object, no markdown fences, no preamble:
{{
    "rule_legality": {{"score": <1-5>, "issues": ["list", "of", "specific", "issues"]}},
    "completeness": {{"score": <1-5>, "missing": ["list", "of", "missing", "elements"]}},
    "concept_fidelity": {{"score": <1-5>, "notes": "brief explanation"}},
    "mechanical_cohesion": {{"score": <1-5>, "notes": "brief explanation"}},
    "creativity": {{"score": <1-5>, "notes": "brief explanation"}},
    "overall_notes": "1-2 sentence overall impression",
    "fabricated_content": ["list any feats, features, or rules that don't exist in PF2e"]
}}
"""

HEAD_TO_HEAD_PROMPT = """\
You are an expert Pathfinder 2nd Edition rules judge. You will compare two character \
builds made from the same prompt and determine which is better.

## The original prompt:
<prompt>
{prompt}
</prompt>

## Build A:
<build_a>
{build_a}
</build_a>

## Build B:
<build_b>
{build_b}
</build_b>

Compare these builds on: rule legality, completeness, concept fidelity, mechanical \
cohesion, and creativity. Then pick a winner.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{{
    "winner": "A" or "B" or "tie",
    "reasoning": "2-3 sentences explaining why",
    "a_strengths": ["list of Build A's advantages"],
    "b_strengths": ["list of Build B's advantages"],
    "confidence": "high" or "medium" or "low"
}}
"""


# ---------------------------------------------------------------------------
# Judge API calls
# ---------------------------------------------------------------------------
def call_judge(judge_key: str, prompt: str, max_retries: int = 2) -> str:
    """Send a scoring prompt to the judge model. Returns raw text response."""
    cfg = JUDGES[judge_key]

    for attempt in range(max_retries + 1):
        try:
            if cfg.get("native_sdk"):
                import anthropic
                client = anthropic.Anthropic(api_key=os.getenv(cfg["env_key"], ""))
                response = client.messages.create(
                    model=cfg["model"],
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,  # low temp for consistent judging
                )
                return response.content[0].text

            elif judge_key == "ollama":
                base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
                client = OpenAI(base_url=base_url, api_key="ollama")
            else:
                client = OpenAI(
                    base_url=cfg["base_url"],
                    api_key=os.getenv(cfg["env_key"], ""),
                )

            response = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
            )
            return response.choices[0].message.content

        except Exception as e:
            if attempt < max_retries:
                print(f"    ⚠ Retry {attempt + 1}: {e}")
                time.sleep(2)
            else:
                raise


def parse_json_response(text: str) -> dict:
    """Extract JSON from a judge response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    # Try to find JSON object boundaries
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        cleaned = cleaned[start:end]
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Scoring modes
# ---------------------------------------------------------------------------
def score_individual(results: list[dict], judge_key: str, prompts: dict) -> list[dict]:
    """Score each build individually against the rubric."""
    scores = []

    for r in results:
        if "error" in r or "content" not in r:
            continue

        prompt_key = r.get("prompt_key", "unknown")
        prompt_content = prompts.get(prompt_key, r.get("prompt_label", "Unknown prompt"))
        provider = r["provider"]
        build_id = f"{prompt_key}/{provider}"

        print(f"  📊 Scoring {build_id:.<50} ", end="", flush=True)

        judge_prompt = INDIVIDUAL_SCORE_PROMPT.format(
            prompt=prompt_content,
            build=r["content"][:8000],  # truncate to avoid context limits
        )

        try:
            raw = call_judge(judge_key, judge_prompt)
            parsed = parse_json_response(raw)

            # Calculate weighted score
            weights = {
                "rule_legality": 0.30,
                "completeness": 0.20,
                "concept_fidelity": 0.20,
                "mechanical_cohesion": 0.15,
                "creativity": 0.15,
            }
            weighted = sum(
                parsed.get(k, {}).get("score", 0) * w
                for k, w in weights.items()
            )

            score_entry = {
                "provider": provider,
                "model": r.get("model", ""),
                "name": r.get("name", ""),
                "prompt_key": prompt_key,
                "scores": parsed,
                "weighted_total": round(weighted, 2),
                "elapsed_s": r.get("elapsed_s"),
                "output_tokens": r.get("output_tokens"),
            }
            scores.append(score_entry)

            print(f"✅ weighted={weighted:.2f}/5.00")

        except Exception as e:
            print(f"❌ {e}")
            scores.append({
                "provider": provider, "prompt_key": prompt_key,
                "error": str(e),
            })

    return scores


def score_head_to_head(results: list[dict], judge_key: str, prompts: dict) -> list[dict]:
    """
    Compare builds pairwise within each prompt. Runs each comparison TWICE
    with reversed order to detect positional bias.
    """
    from itertools import combinations

    comparisons = []

    # Group results by prompt
    by_prompt = {}
    for r in results:
        if "error" not in r and "content" in r:
            by_prompt.setdefault(r.get("prompt_key", "unknown"), []).append(r)

    for prompt_key, builds in by_prompt.items():
        prompt_content = prompts.get(prompt_key, "Unknown prompt")
        print(f"\n  Head-to-head for: {prompt_key}")

        for a, b in combinations(builds, 2):
            pair_label = f"{a['provider']} vs {b['provider']}"
            print(f"    🥊 {pair_label:.<45} ", end="", flush=True)

            try:
                # Round 1: A first, B second
                prompt_1 = HEAD_TO_HEAD_PROMPT.format(
                    prompt=prompt_content,
                    build_a=a["content"][:6000],
                    build_b=b["content"][:6000],
                )
                raw_1 = call_judge(judge_key, prompt_1)
                result_1 = parse_json_response(raw_1)

                # Round 2: B first, A second (detect positional bias)
                prompt_2 = HEAD_TO_HEAD_PROMPT.format(
                    prompt=prompt_content,
                    build_a=b["content"][:6000],
                    build_b=a["content"][:6000],
                )
                raw_2 = call_judge(judge_key, prompt_2)
                result_2 = parse_json_response(raw_2)

                # Reconcile — flip round 2 back to original orientation
                r2_winner = {"A": "B", "B": "A", "tie": "tie"}.get(result_2["winner"], "tie")

                if result_1["winner"] == r2_winner:
                    final_winner = result_1["winner"]
                    consistency = "consistent"
                else:
                    final_winner = "tie (positional bias detected)"
                    consistency = "inconsistent"

                # Map A/B back to provider names
                winner_name = (
                    a["provider"] if final_winner == "A"
                    else b["provider"] if final_winner == "B"
                    else final_winner
                )

                comp = {
                    "prompt_key": prompt_key,
                    "provider_a": a["provider"],
                    "provider_b": b["provider"],
                    "round_1": result_1,
                    "round_2_flipped": {**result_2, "original_winner": r2_winner},
                    "final_winner": winner_name,
                    "consistency": consistency,
                }
                comparisons.append(comp)
                print(f"✅ winner={winner_name} ({consistency})")

            except Exception as e:
                print(f"❌ {e}")
                comparisons.append({
                    "prompt_key": prompt_key,
                    "provider_a": a["provider"],
                    "provider_b": b["provider"],
                    "error": str(e),
                })

    return comparisons


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(
    scores: list[dict],
    comparisons: list[dict],
    judge_key: str,
    output_path: Path,
):
    """Generate a markdown comparison report."""
    lines = [
        "# PF2e Character Build — Model Comparison Report",
        f"\n**Judge model:** {JUDGES[judge_key]['name']}  ",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}  ",
        "",
    ]

    # ── Individual scores table ──
    if scores:
        lines.append("## Individual Scores\n")

        # Group by prompt
        by_prompt = {}
        for s in scores:
            if "error" not in s:
                by_prompt.setdefault(s["prompt_key"], []).append(s)

        for prompt_key, prompt_scores in by_prompt.items():
            lines.append(f"### {prompt_key}\n")
            lines.append(
                "| Provider | Legality | Complete | Concept | Cohesion | "
                "Creative | **Weighted** | Time | Tokens |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|")

            prompt_scores.sort(key=lambda x: x["weighted_total"], reverse=True)
            for s in prompt_scores:
                sc = s["scores"]
                lines.append(
                    f"| {s.get('name', s['provider'])} "
                    f"| {sc.get('rule_legality', {}).get('score', '?')} "
                    f"| {sc.get('completeness', {}).get('score', '?')} "
                    f"| {sc.get('concept_fidelity', {}).get('score', '?')} "
                    f"| {sc.get('mechanical_cohesion', {}).get('score', '?')} "
                    f"| {sc.get('creativity', {}).get('score', '?')} "
                    f"| **{s['weighted_total']:.2f}** "
                    f"| {s.get('elapsed_s', '?')}s "
                    f"| {s.get('output_tokens', '?')} |"
                )

            # Fabricated content flags
            for s in prompt_scores:
                fab = s["scores"].get("fabricated_content", [])
                if fab:
                    lines.append(f"\n⚠ **{s.get('name', s['provider'])}** — "
                                 f"Fabricated content detected: {', '.join(fab)}")

            # Rule legality issues
            for s in prompt_scores:
                issues = s["scores"].get("rule_legality", {}).get("issues", [])
                if issues:
                    lines.append(f"\n🔍 **{s.get('name', s['provider'])}** — "
                                 f"Rule issues: {'; '.join(issues[:5])}")
            lines.append("")

        # ── Aggregate rankings ──
        lines.append("## Aggregate Rankings (across all prompts)\n")
        agg = {}
        for s in scores:
            if "error" not in s:
                p = s["provider"]
                if p not in agg:
                    agg[p] = {"name": s.get("name", p), "totals": [], "times": []}
                agg[p]["totals"].append(s["weighted_total"])
                if s.get("elapsed_s"):
                    agg[p]["times"].append(s["elapsed_s"])

        ranked = []
        for p, data in agg.items():
            avg = sum(data["totals"]) / len(data["totals"])
            avg_time = sum(data["times"]) / len(data["times"]) if data["times"] else 0
            ranked.append((data["name"], avg, avg_time, len(data["totals"])))

        ranked.sort(key=lambda x: x[1], reverse=True)
        lines.append("| Rank | Provider | Avg Score | Avg Time | Prompts Tested |")
        lines.append("|---|---|---|---|---|")
        for i, (name, avg, avg_time, count) in enumerate(ranked, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            lines.append(f"| {medal} | {name} | **{avg:.2f}**/5.00 | {avg_time:.1f}s | {count} |")
        lines.append("")

    # ── Head-to-head results ──
    if comparisons:
        lines.append("## Head-to-Head Comparisons\n")

        for c in comparisons:
            if "error" in c:
                continue
            lines.append(
                f"- **{c['provider_a']}** vs **{c['provider_b']}** "
                f"({c['prompt_key']}): winner = **{c['final_winner']}** "
                f"[{c['consistency']}]"
            )
            if c.get("round_1", {}).get("reasoning"):
                lines.append(f"  > {c['round_1']['reasoning']}")

        # Win tally
        lines.append("\n### Win Tally\n")
        wins = {}
        for c in comparisons:
            if "error" not in c:
                w = c["final_winner"]
                if w not in ("tie", "tie (positional bias detected)"):
                    wins[w] = wins.get(w, 0) + 1
        if wins:
            lines.append("| Provider | Wins |")
            lines.append("|---|---|")
            for p, count in sorted(wins.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| {p} | {count} |")
        lines.append("")

    report = "\n".join(lines)
    output_path.write_text(report)
    print(f"\n📄 Report saved to {output_path}")
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Score PF2e character builds with LLM-as-judge")
    parser.add_argument(
        "results_file",
        type=str,
        help="Path to the _results.json file from test_chargen.py",
    )
    parser.add_argument(
        "--judge",
        type=str,
        choices=list(JUDGES.keys()),
        default="gemini",
        help="Which model to use as judge (default: gemini — free)",
    )
    parser.add_argument(
        "--head-to-head",
        action="store_true",
        help="Also run pairwise comparisons (doubled API calls for bias detection)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same as results file)",
    )
    args = parser.parse_args()

    # Load results
    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"File not found: {results_path}")
        sys.exit(1)

    results = json.loads(results_path.read_text())
    print(f"Loaded {len(results)} build results from {results_path}")

    # Check judge availability
    judge_cfg = JUDGES[args.judge]
    if judge_cfg.get("native_sdk"):
        if not os.getenv(judge_cfg["env_key"], "").strip():
            print(f"Judge model {args.judge} requires API key ({judge_cfg['env_key']})")
            sys.exit(1)
    elif args.judge == "ollama":
        pass  # will fail at call time if not running
    elif not os.getenv(judge_cfg.get("env_key", ""), "").strip():
        print(f"Judge model {args.judge} requires API key ({judge_cfg.get('env_key')})")
        sys.exit(1)

    print(f"Using judge: {judge_cfg['name']}\n")

    # Reconstruct prompt content for the judge
    # Import prompts from test_chargen
    from test_chargen import PROMPTS
    prompt_content_map = {k: v["content"] for k, v in PROMPTS.items()}

    # Individual scoring
    print("Phase 1: Individual scoring")
    print("-" * 40)
    scores = score_individual(results, args.judge, prompt_content_map)

    # Head-to-head (optional)
    comparisons = []
    if args.head_to_head:
        print(f"\nPhase 2: Head-to-head comparisons (with bias detection)")
        print("-" * 40)
        comparisons = score_head_to_head(results, args.judge, prompt_content_map)

    # Generate report
    out_dir = Path(args.output_dir) if args.output_dir else results_path.parent
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"{ts}_scores_{args.judge}.md"
    scores_json_path = out_dir / f"{ts}_scores_{args.judge}.json"

    generate_report(scores, comparisons, args.judge, report_path)

    # Save raw scores JSON
    scores_json_path.write_text(json.dumps({
        "judge": args.judge,
        "individual_scores": scores,
        "head_to_head": comparisons,
    }, indent=2, default=str))
    print(f"📊 Raw scores saved to {scores_json_path}")


if __name__ == "__main__":
    main()
