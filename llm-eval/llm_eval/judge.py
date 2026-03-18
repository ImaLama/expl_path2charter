"""
LLM-as-Judge scoring engine.

Individual scoring: sends each result to a judge model with the pack's rubric.
Head-to-head: pairwise comparisons run twice with reversed order for bias detection.
"""

from __future__ import annotations

import json
import re
from itertools import combinations

from .providers import call_provider, get_all_providers
from .types import (
    ChallengePack,
    GenerationResult,
    HeadToHeadResult,
    IndividualScore,
)


def _build_individual_prompt(
    pack: ChallengePack,
    original_prompt: str,
    response_content: str,
) -> str:
    """Build the judge prompt for individual scoring."""
    rubric = pack.get_rubric()

    criteria_text = ""
    for i, c in enumerate(rubric.criteria, 1):
        criteria_text += f"\n### {i}. {c.label} (weight: {c.weight:.0%})\n{c.description}\n"

    schema_text = json.dumps(rubric.output_schema, indent=2)

    return f"""{rubric.judge_preamble}

## The original prompt given to the model:
<prompt>
{original_prompt}
</prompt>

## The model's response to evaluate:
<response>
{response_content[:8000]}
</response>

## Scoring rubric — score each criterion from 1 (terrible) to 5 (flawless):
{criteria_text}

## Response format
Respond with ONLY a JSON object matching this schema. No markdown fences, no preamble:
{schema_text}

Include an "overall_notes" field with a 1-2 sentence overall impression."""


def _build_head_to_head_prompt(
    pack: ChallengePack,
    original_prompt: str,
    response_a: str,
    response_b: str,
) -> str:
    """Build the judge prompt for head-to-head comparison."""
    rubric = pack.get_rubric()
    criteria_names = ", ".join(c.label.lower() for c in rubric.criteria)

    return f"""{rubric.judge_preamble}

You will compare two responses to the same prompt and determine which is better.

## The original prompt:
<prompt>
{original_prompt}
</prompt>

## Response A:
<response_a>
{response_a[:6000]}
</response_a>

## Response B:
<response_b>
{response_b[:6000]}
</response_b>

Compare these responses on: {criteria_names}. Then pick a winner.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{{
    "winner": "A" or "B" or "tie",
    "reasoning": "2-3 sentences explaining why",
    "a_strengths": ["list of Response A's advantages"],
    "b_strengths": ["list of Response B's advantages"],
    "confidence": "high" or "medium" or "low"
}}"""


def _parse_json_response(text: str) -> dict:
    """Extract JSON from a judge response, handling markdown fences."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        cleaned = cleaned[start:end]
    return json.loads(cleaned)


def _call_judge(judge_key: str, prompt: str) -> str:
    """Call the judge model and return raw text."""
    providers = get_all_providers()
    cfg = providers[judge_key]
    result = call_provider(
        cfg, prompt, temperature=0.2, max_tokens=2048, max_retries=3
    )
    if result.error:
        raise RuntimeError(f"Judge call failed: {result.error}")
    return result.content


def score_individual(
    results: list[GenerationResult],
    pack: ChallengePack,
    judge_provider: str,
) -> list[IndividualScore]:
    """Score each result individually using the judge model."""
    rubric = pack.get_rubric()
    auto_scorer = pack.get_auto_scorer()
    auto_weight = pack.get_auto_score_weight()
    scores: list[IndividualScore] = []

    # Build prompt lookup from pack
    prompt_map = {p.key: p for p in pack.get_prompts()}

    for r in results:
        if r.error:
            continue

        build_id = f"{r.prompt_key}/{r.provider}"
        print(f"  Scoring {build_id:.<50} ", end="", flush=True)

        prompt_obj = prompt_map.get(r.prompt_key)
        original_prompt = prompt_obj.content if prompt_obj else r.prompt_label

        judge_prompt = _build_individual_prompt(pack, original_prompt, r.content)

        try:
            raw = _call_judge(judge_provider, judge_prompt)
            parsed = _parse_json_response(raw)

            # Compute weighted total from judge scores
            judge_weighted = sum(
                parsed.get(c.key, {}).get("score", 0) * c.weight
                for c in rubric.criteria
            )

            # Auto-scoring if available
            auto_scores = None
            if auto_scorer and prompt_obj:
                try:
                    auto_scores = auto_scorer.score(prompt_obj, r)
                except Exception as e:
                    print(f"(auto-score failed: {e}) ", end="")

            # Merge scores
            if auto_scores and auto_weight > 0:
                auto_total = sum(
                    v.get("score", 0) for v in auto_scores.values()
                ) / max(len(auto_scores), 1)
                # Normalize auto_total to same 1-5 scale
                final_weighted = (
                    judge_weighted * (1 - auto_weight)
                    + auto_total * auto_weight
                )
            else:
                final_weighted = judge_weighted

            score = IndividualScore(
                provider=r.provider,
                model=r.model,
                name=r.name,
                prompt_key=r.prompt_key,
                scores=parsed,
                weighted_total=round(final_weighted, 2),
                auto_scores=auto_scores,
                elapsed_s=r.elapsed_s,
                output_tokens=r.output_tokens,
            )
            scores.append(score)
            print(f"OK weighted={final_weighted:.2f}/5.00")

        except Exception as e:
            print(f"ERROR: {e}")

    return scores


def score_head_to_head(
    results: list[GenerationResult],
    pack: ChallengePack,
    judge_provider: str,
) -> list[HeadToHeadResult]:
    """Run pairwise comparisons with bias detection."""
    h2h_results: list[HeadToHeadResult] = []

    # Build prompt lookup
    prompt_map = {p.key: p for p in pack.get_prompts()}

    # Group results by prompt
    by_prompt: dict[str, list[GenerationResult]] = {}
    for r in results:
        if not r.error:
            by_prompt.setdefault(r.prompt_key, []).append(r)

    for prompt_key, builds in by_prompt.items():
        prompt_obj = prompt_map.get(prompt_key)
        original_prompt = prompt_obj.content if prompt_obj else prompt_key
        print(f"\n  Head-to-head for: {prompt_key}")

        for a, b in combinations(builds, 2):
            pair_label = f"{a.provider} vs {b.provider}"
            print(f"    {pair_label:.<45} ", end="", flush=True)

            try:
                # Round 1: A first, B second
                prompt_1 = _build_head_to_head_prompt(
                    pack, original_prompt, a.content, b.content
                )
                raw_1 = _call_judge(judge_provider, prompt_1)
                result_1 = _parse_json_response(raw_1)

                # Round 2: B first, A second (detect positional bias)
                prompt_2 = _build_head_to_head_prompt(
                    pack, original_prompt, b.content, a.content
                )
                raw_2 = _call_judge(judge_provider, prompt_2)
                result_2 = _parse_json_response(raw_2)

                # Flip round 2 back to original orientation
                r1_winner = result_1.get("winner", "tie")
                r2_raw = result_2.get("winner", "tie")
                r2_winner = {"A": "B", "B": "A", "tie": "tie"}.get(r2_raw, "tie")

                if r1_winner == r2_winner:
                    consistency = "consistent"
                    final_letter = r1_winner
                else:
                    consistency = "inconsistent"
                    final_letter = "tie"

                # Map A/B to provider names
                final_winner = (
                    a.provider if final_letter == "A"
                    else b.provider if final_letter == "B"
                    else "tie"
                )

                reasoning = result_1.get("reasoning", "")

                h2h_results.append(HeadToHeadResult(
                    prompt_key=prompt_key,
                    provider_a=a.provider,
                    provider_b=b.provider,
                    round_1_winner=r1_winner,
                    round_2_winner=r2_winner,
                    final_winner=final_winner,
                    consistency=consistency,
                    reasoning=reasoning,
                ))
                print(f"OK winner={final_winner} ({consistency})")

            except Exception as e:
                print(f"ERROR: {e}")

    return h2h_results
