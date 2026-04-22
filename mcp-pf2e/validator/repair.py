"""Format validation errors as an LLM repair prompt."""

from .types import ValidationResult


def format_repair_prompt(
    result: ValidationResult,
    original_prompt: str = "",
    history: list[dict] | None = None,
    valid_skill_feats: dict[str, list[str]] | None = None,
) -> str:
    """Format validation errors into a repair prompt with cumulative history.

    Args:
        result: Current validation result
        original_prompt: The original build request
        history: List of previous attempts, each with:
            {"attempt": N, "errors": [{"rule": ..., "message": ..., "feat_name": ...}]}
        valid_skill_feats: Optional dict of {skill_name: [feat_names]} for narrowed replacements.
            When provided, appended as a "valid skill feats" section to guide repair.
    """
    if result.is_valid:
        return ""

    lines = []

    if original_prompt:
        lines.append(f"Original request: {original_prompt}")
        lines.append("")

    # Cumulative history — show what was already tried and failed
    if history:
        failed_names = set()
        lines.append("=== PREVIOUS FAILED ATTEMPTS ===")
        for h in history:
            lines.append(f"Attempt {h['attempt']}:")
            for err in h["errors"]:
                lines.append(f"  - {err['message']}")
                if err.get("feat_name"):
                    failed_names.add(err["feat_name"])
        lines.append("")

        if failed_names:
            lines.append(f"Do NOT use any of these (all invalid): {', '.join(sorted(failed_names))}")
            lines.append("")

    lines.append(f"Your build STILL has {result.error_count} error(s):" if history else f"Your build had {result.error_count} error(s):")
    lines.append("")

    for i, error in enumerate(result.errors, 1):
        rule_label = error.rule.upper().replace("_", " ")
        lines.append(f"{i}. [{rule_label}] {error.message}")

        if error.details.get("suggestion"):
            lines.append(f"   Suggestion: use \"{error.details['suggestion']}\" instead.")

    if result.warnings:
        lines.append("")
        lines.append("Warnings (non-blocking):")
        for w in result.warnings:
            lines.append(f"  - [{w.rule}] {w.message}")

    # Valid skill feats section — guides repair toward actually eligible choices
    if valid_skill_feats:
        has_prereq_error = any(
            e.rule == "prerequisite" for e in result.errors
        )
        if has_prereq_error:
            lines.append("")
            lines.append("=== VALID SKILL FEATS FOR YOUR TRAINED SKILLS ===")
            lines.append("Pick skill feat replacements ONLY from this list:")
            for skill_name in sorted(valid_skill_feats):
                feat_names = valid_skill_feats[skill_name]
                if feat_names:
                    lines.append(f"  {skill_name}: {', '.join(sorted(feat_names))}")

    lines.append("")
    lines.append("Fix ONLY the errors listed above. Keep all other choices the same.")
    lines.append("Output the complete corrected build as valid JSON.")

    return "\n".join(lines)
