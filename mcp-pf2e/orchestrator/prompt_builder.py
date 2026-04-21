"""Build prompts for PF2e character generation with decomposed feat options."""

import json

from query.types import BuildOptions, SlotOptions


_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. You have deep knowledge \
of all official PF2e rules, classes, ancestries, feats, and equipment.

CRITICAL RULES:
- ONLY use feats, spells, and features from the provided option lists.
- Do NOT invent or fabricate any game content.
- Each feat slot must be filled with exactly one feat from the corresponding list.
- Feat prerequisites must be satisfied (a feat requiring another feat means that feat was taken at an earlier level).
- Ability scores use the standard boost system: 4 free boosts at level 1, plus ancestry/background/class boosts.
- Ability scores must be RAW SCORES (e.g., 10, 12, 14, 16, 18), NOT modifiers. A boost raises a score by 2 (e.g., 10 → 12). Starting base is 10 for all abilities.
- For general and skill feat slots, use ONLY real PF2e feat names (e.g., "Intimidating Glare", "Assurance", "Toughness"). Do NOT use skill names or generic terms as feat names.

IMPORTANT: Skill feat slots require FEAT NAMES like "Intimidating Glare" or "Assurance", \
NOT skill names like "Stealth", "Athletics", or "Deception". Skills and skill feats are different things.

Output your build as valid JSON matching the schema provided in the prompt."""


_JSON_SCHEMA_TEMPLATE = """\
Output ONLY valid JSON with this exact structure (no markdown, no explanation outside the JSON):

{{
  "class": "{class_name}",
  "ancestry": "{ancestry_name}",
  "heritage": "<choose an appropriate heritage>",
  "background": "<choose a background>",
  "level": {level},
  "ability_scores": {{"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 12, "cha": 18}},
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


def _append_grouped_skill_feats(parts: list[str], so: SlotOptions):
    """Append skill feats grouped by prerequisite skill."""
    groups: dict[str, list[str]] = {}
    for opt in so.options:
        if not opt.prerequisites:
            groups.setdefault("Any (no prerequisite)", []).append(opt.name)
            continue
        prereq_lower = opt.prerequisites.lower()
        placed = False
        for skill in [
            "acrobatics", "arcana", "athletics", "crafting", "deception",
            "diplomacy", "intimidation", "medicine", "nature", "occultism",
            "performance", "religion", "society", "stealth", "survival", "thievery",
        ]:
            if skill in prereq_lower:
                groups.setdefault(f"{skill.title()} (trained)", []).append(opt.name)
                placed = True
                break
        if not placed:
            groups.setdefault("Other", []).append(opt.name)

    parts.append(f"  SKILL FEAT slot ({len(so.options)} options, grouped by prerequisite skill):")
    parts.append(f"  These are FEAT NAMES — do NOT use skill names like 'Stealth' or 'Athletics'.")
    for group_name in sorted(groups):
        names = sorted(groups[group_name])
        parts.append(f"    {group_name}: {', '.join(names)}")


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

    # Feat options per slot — all types now listed (skill feats pre-filtered by prereqs)
    parts.append("=== AVAILABLE FEAT OPTIONS ===")
    parts.append("You MUST choose feats ONLY from these lists. Do NOT use any feat not listed here.")
    parts.append("")

    slots_by_level: dict[int, list] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    # Track which skill feat options we've already printed (shared across levels)
    skill_feats_printed = False

    for level in sorted(slots_by_level):
        parts.append(f"--- Level {level} ---")
        for so in slots_by_level[level]:
            slot_label = so.slot.slot_type.upper()

            if so.slot.slot_type == "skill":
                if not skill_feats_printed:
                    _append_grouped_skill_feats(parts, so)
                    skill_feats_printed = True
                else:
                    parts.append(f"  {slot_label} FEAT slot: pick from the skill feat list above (level {level} or lower)")
            elif len(so.options) > 30:
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options):")
                names = [opt.name for opt in so.options]
                parts.append(f"    {', '.join(names)}")
            else:
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options):")
                for opt in so.options:
                    line = f"    - {opt.name} (lvl {opt.level})"
                    if opt.prerequisites:
                        line += f" [prereq: {opt.prerequisites}]"
                    if opt.rarity != "common":
                        line += f" [{opt.rarity}]"
                    parts.append(line)
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
