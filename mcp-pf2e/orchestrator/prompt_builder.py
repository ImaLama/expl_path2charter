"""Build prompts for PF2e character generation with decomposed feat options."""

import json

from query.types import BuildOptions


_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. You have deep knowledge \
of all official PF2e rules, classes, ancestries, feats, and equipment.

CRITICAL RULES:
- ONLY use feats, spells, and features from the provided option lists.
- Do NOT invent or fabricate any game content.
- Each feat slot must be filled with exactly one feat from the corresponding list.
- Feat prerequisites must be satisfied (a feat requiring another feat means that feat was taken at an earlier level).
- Ability scores use the standard boost system: 4 free boosts at level 1, plus ancestry/background/class boosts.

Output your build as valid JSON matching the schema provided in the prompt."""


_JSON_SCHEMA_TEMPLATE = """\
Output ONLY valid JSON with this exact structure (no markdown, no explanation outside the JSON):

{{
  "class": "{class_name}",
  "ancestry": "{ancestry_name}",
  "heritage": "<choose an appropriate heritage>",
  "background": "<choose a background>",
  "level": {level},
  "ability_scores": {{"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0}},
  "levels": {{
{level_slots}
  }},
  "equipment": ["<item1>", "<item2>"],
  "notes": "<brief build rationale>"
}}"""


_MARKDOWN_TEMPLATE = """\
Use this exact format:

## Character Summary
Class: {class_name}
Ancestry: {ancestry_name}
Heritage: <choose>
Background: <choose>
Level: {level}

## Ability Scores
STR: X, DEX: X, CON: X, INT: X, WIS: X, CHA: X

{level_sections}

## Equipment
- <item list>

## Notes
<brief build rationale>"""


def build_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_generation_prompt(
    request: str,
    options: BuildOptions,
    output_format: str = "json",
) -> str:
    """Build a prompt with decomposed feat options and output template.

    Args:
        request: Free-text build request or flavor text
        options: Decomposed build options from the decomposer
        output_format: "json" or "markdown"
    """
    parts = []

    # Build request
    parts.append(f"Build request: {request}")
    parts.append("")

    # Feat options per slot — only list class-specific feats to save tokens
    # General and skill feats are too numerous to list (100+)
    DETAILED_SLOT_TYPES = {"class", "ancestry"}
    SUMMARY_SLOT_TYPES = {"general", "skill"}

    parts.append("=== AVAILABLE FEAT OPTIONS ===")
    parts.append("Choose feats from these lists. For class and ancestry feats, you MUST pick from the options below.")
    parts.append("For general and skill feats, choose any valid PF2e feat of the appropriate type and level.")
    parts.append("")

    slots_by_level: dict[int, list] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    for level in sorted(slots_by_level):
        parts.append(f"--- Level {level} ---")
        for so in slots_by_level[level]:
            slot_label = so.slot.slot_type.upper()
            if so.slot.slot_type in DETAILED_SLOT_TYPES:
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options):")
                for opt in so.options:
                    line = f"    - {opt.name} (lvl {opt.level})"
                    if opt.prerequisites:
                        line += f" [prereq: {opt.prerequisites}]"
                    if opt.rarity != "common":
                        line += f" [{opt.rarity}]"
                    parts.append(line)
            else:
                parts.append(f"  {slot_label} FEAT slot: choose any {so.slot.slot_type} feat of level {level} or lower")
        parts.append("")

    # Output format template
    parts.append("=== OUTPUT FORMAT ===")

    if output_format == "json":
        level_slot_lines = _build_json_level_slots(options)
        schema = _JSON_SCHEMA_TEMPLATE.format(
            class_name=options.spec.class_name.title(),
            ancestry_name=options.spec.ancestry_name.title() if options.spec.ancestry_name else "<ancestry>",
            level=options.spec.character_level,
            level_slots=level_slot_lines,
        )
        parts.append(schema)
    else:
        level_sections = _build_markdown_level_sections(options)
        template = _MARKDOWN_TEMPLATE.format(
            class_name=options.spec.class_name.title(),
            ancestry_name=options.spec.ancestry_name.title() if options.spec.ancestry_name else "<ancestry>",
            level=options.spec.character_level,
            level_sections=level_sections,
        )
        parts.append(template)

    return "\n".join(parts)


def _build_json_level_slots(options: BuildOptions) -> str:
    """Build the levels dict template for JSON schema."""
    slots_by_level: dict[int, list] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    lines = []
    levels = sorted(slots_by_level)
    for i, level in enumerate(levels):
        slot_parts = []
        for so in slots_by_level[level]:
            key = f"{so.slot.slot_type}_feat"
            slot_parts.append(f'"{key}": "<name from {so.slot.slot_type} list>"')
        slots_str = ", ".join(slot_parts)
        comma = "," if i < len(levels) - 1 else ""
        lines.append(f'    "{level}": {{{slots_str}}}{comma}')
    return "\n".join(lines)


def _build_markdown_level_sections(options: BuildOptions) -> str:
    """Build level sections for markdown template."""
    slots_by_level: dict[int, list] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    sections = []
    for level in sorted(slots_by_level):
        lines = [f"## Level {level}"]
        for so in slots_by_level[level]:
            label = so.slot.slot_type.title()
            lines.append(f"- {label} Feat: <name from {so.slot.slot_type} list>")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
