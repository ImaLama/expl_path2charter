"""LLM-as-judge evaluator for PF2e character builds."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.pipeline import _call_ollama

EVAL_PROMPT = """\
You are evaluating a Pathfinder 2nd Edition character build for quality.

Build request: "{request}"
Expected themes: {themes}

Generated build:
{build_json}

Validation result: {validation_summary}

Score on two dimensions (1-10 each):

THEME (does the build match the requested concept?):
- 9-10: Every choice serves the concept
- 7-8: Most choices fit, minor misses
- 5-6: Mixed, some choices seem random
- 3-4: Weak connection to concept
- 1-2: Build ignores the concept

SYNERGY (do the choices work together mechanically?):
- 9-10: Choices create strong combos and action economy
- 7-8: Solid choices, no wasted picks
- 5-6: Some choices don't contribute to the build
- 3-4: Contradictory or redundant picks
- 1-2: Random selection with no coherent strategy

Return ONLY this JSON, no other text:
{{"theme_score": <int 1-10>, "synergy_score": <int 1-10>, "overall_score": <number 1-10>, "notes": "<2-3 sentences explaining scores>"}}"""

EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "theme_score": {"type": "integer"},
        "synergy_score": {"type": "integer"},
        "overall_score": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["theme_score", "synergy_score", "overall_score", "notes"],
}


def evaluate_build(
    request: str,
    expect_themes: list[str],
    build_json: dict | None,
    build_text: str,
    validation: dict,
    judge_model: str,
) -> dict:
    """Score a build using an LLM judge. Returns dict with scores and notes."""
    build_display = json.dumps(build_json, indent=2) if build_json else build_text

    valid_str = "VALID" if validation.get("is_valid") else "INVALID"
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    validation_summary = f"{valid_str}, {len(errors)} errors, {len(warnings)} warnings"
    if errors:
        validation_summary += "\nErrors: " + "; ".join(
            e["message"] if isinstance(e, dict) else str(e) for e in errors[:5]
        )

    prompt = EVAL_PROMPT.format(
        request=request,
        themes=", ".join(expect_themes),
        build_json=build_display,
        validation_summary=validation_summary,
    )

    content, elapsed, usage = _call_ollama(
        model=judge_model,
        prompt=prompt,
        system_prompt="You are a PF2e rules expert scoring character builds. Return only valid JSON.",
        temperature=0.2,
        json_mode=False,
        response_schema=EVAL_SCHEMA,
        max_tokens=1024,
    )

    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        scores = {
            "theme_score": 0,
            "synergy_score": 0,
            "overall_score": 0,
            "notes": f"Judge parse error: {content[:200]}",
        }

    return {
        "theme_score": scores.get("theme_score", 0),
        "synergy_score": scores.get("synergy_score", 0),
        "overall_score": scores.get("overall_score", 0),
        "evaluator_notes": scores.get("notes", ""),
        "judge_time": elapsed,
        "judge_tokens": usage,
    }
