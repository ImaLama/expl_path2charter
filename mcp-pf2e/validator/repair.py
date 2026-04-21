"""Format validation errors as an LLM repair prompt."""

from .types import ValidationResult


def format_repair_prompt(result: ValidationResult, original_prompt: str = "") -> str:
    """Format validation errors into a repair prompt for the LLM.

    The repair prompt tells the model exactly what's wrong and asks it to
    fix only those issues, keeping everything else the same.
    """
    if result.is_valid:
        return ""

    lines = []

    if original_prompt:
        lines.append(f"Original request: {original_prompt}")
        lines.append("")

    lines.append(f"Your build had {result.error_count} error(s):")
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

    lines.append("")
    lines.append("Fix ONLY the errors listed above. Keep all other choices the same.")
    lines.append("Output the complete corrected build.")

    return "\n".join(lines)
