"""Build prompts for PF2e character generation with decomposed feat options."""

import copy
import json

from query.types import BuildOptions, SlotOptions
from query.static_reader import list_available_classes, list_available_ancestries, list_heritages, list_backgrounds, list_skill_feats_for_skills, _ALL_SKILLS


_SKELETON_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. Given a character concept, \
choose the best class, ancestry, heritage, background, and level.

Consider synergies: ancestry attribute bonuses, heritage abilities, class key abilities, \
and background skill training should all support the concept.

Output ONLY valid JSON, no explanation."""


_SKELETON_USER_TEMPLATE = """\
Character concept: {request}

{constraints}

Choose class, ancestry, heritage, background, and level for this concept.
Consider which ancestry has the best attribute bonuses and abilities for this build.

Available classes: {classes}
Available ancestries: {ancestries}
{heritage_section}
IMPORTANT: Heritage and background MUST be real PF2e names from official content. Do NOT invent them.

Output this JSON structure:
{{
  "class": "<class name>",
  "ancestry": "<ancestry name>",
  "heritage": "<real heritage name from the list above>",
  "background": "<real background name>",
  "level": <integer 1-20>,
  "reasoning": "<1-2 sentences explaining your choices>"
}}"""


_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. You have deep knowledge \
of all official PF2e rules, classes, ancestries, feats, and equipment.

CRITICAL RULES:
- ONLY use feats, spells, and features from the provided option lists.
- Do NOT invent or fabricate any game content.
- Each feat slot must be filled with exactly one feat from the corresponding list.
- Each feat can only be taken ONCE across all levels unless explicitly marked as repeatable (e.g., "Additional Lore", "Assurance"). Never select the same feat for multiple level slots.
- Dedication feats (archetypes) follow special rules: you must take at least 2 non-dedication feats from an archetype before taking a second Dedication feat.
- Feat prerequisites must be satisfied (a feat requiring another feat means that feat was taken at an earlier level).
- Ability scores use the standard boost system: 4 free boosts at level 1, plus ancestry/background/class boosts.
- Ability scores must be RAW SCORES (e.g., 10, 12, 14, 16, 18, 19), NOT modifiers. A boost raises a score by 2 (or by 1 if the score is already 18 or higher). Starting base is 10 for all abilities.
- In the "skills" field, list ALL skills the character is trained or better in, with rank: "trained", "expert", "master", or "legendary". Skills come from: class training, background, and skill increases at odd levels (3, 5, 7, ...). Expert requires level 3+, master requires level 7+, legendary requires level 15+.
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
  "skills": {{"athletics": "trained", "intimidation": "trained", "occultism": "trained"}},
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


def build_skeleton_prompts(
    request: str,
    class_name: str = "",
    ancestry_name: str = "",
    level: int = 0,
) -> tuple[str, str]:
    """Build system + user prompts for the skeleton pass.

    Returns (system_prompt, user_prompt).
    """
    constraints = []
    if class_name:
        constraints.append(f"Class MUST be: {class_name}")
    if ancestry_name:
        constraints.append(f"Ancestry MUST be: {ancestry_name}")
    if level:
        constraints.append(f"Level MUST be: {level}")

    constraint_str = "\n".join(constraints) if constraints else "No constraints — choose freely."

    classes = ", ".join(list_available_classes())
    ancestries = ", ".join(list_available_ancestries())

    # If ancestry is known, list available heritages
    heritage_section = ""
    if ancestry_name:
        heritages = list_heritages(ancestry_name)
        if heritages:
            heritage_section = f"Available {ancestry_name.title()} heritages: {', '.join(heritages)}"
    if not heritage_section:
        heritage_section = "Heritage: pick a real heritage that matches the chosen ancestry."

    user_prompt = _SKELETON_USER_TEMPLATE.format(
        request=request,
        constraints=constraint_str,
        classes=classes,
        ancestries=ancestries,
        heritage_section=heritage_section,
    )

    return _SKELETON_SYSTEM_PROMPT, user_prompt


def build_skeleton_schema() -> dict:
    """Build JSON schema for the skeleton pass with class/ancestry/background enums."""
    return {
        "type": "object",
        "properties": {
            "class": {"type": "string", "enum": list_available_classes()},
            "ancestry": {"type": "string", "enum": list_available_ancestries()},
            "heritage": {"type": "string"},
            "background": {"type": "string", "enum": list_backgrounds()},
            "level": {"type": "integer"},
            "reasoning": {"type": "string"},
        },
        "required": ["class", "ancestry", "heritage", "background", "level", "reasoning"],
    }


def build_response_schema(options: BuildOptions) -> dict:
    """Build JSON schema with enum constraints for all feat slots.

    Heritage and background are also enum-constrained.
    Each feat slot is a string enum of valid feat names.
    """
    # Heritage enum (depends on ancestry)
    heritage_prop = {"type": "string"}
    if options.spec.ancestry_name:
        heritages = list_heritages(options.spec.ancestry_name)
        if heritages:
            heritage_prop = {"type": "string", "enum": heritages}

    # Background enum
    backgrounds = list_backgrounds()
    background_prop = {"type": "string", "enum": backgrounds} if backgrounds else {"type": "string"}

    # Ability scores
    ability_props = {a: {"type": "integer"} for a in ["str", "dex", "con", "int", "wis", "cha"]}

    # Skills
    skills_prop = {
        "type": "object",
        "additionalProperties": {
            "type": "string",
            "enum": ["trained", "expert", "master", "legendary"],
        },
    }

    # Build per-level feat slot properties with enums
    slots_by_level: dict[int, list[SlotOptions]] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    level_props = {}
    for level in sorted(slots_by_level):
        slot_props = {}
        slot_required = []
        for so in slots_by_level[level]:
            key = f"{so.slot.slot_type}_feat"
            feat_names = sorted(set(o.name for o in so.options))
            slot_props[key] = {"type": "string", "enum": feat_names}
            slot_required.append(key)
        level_props[str(level)] = {
            "type": "object",
            "properties": slot_props,
            "required": slot_required,
        }

    # Lock class/ancestry to known values — prevents identity drift
    class_prop = {"type": "string", "enum": [options.spec.class_name]}
    ancestry_prop = (
        {"type": "string", "enum": [options.spec.ancestry_name]}
        if options.spec.ancestry_name
        else {"type": "string"}
    )

    return {
        "type": "object",
        "properties": {
            "class": class_prop,
            "ancestry": ancestry_prop,
            "heritage": heritage_prop,
            "background": background_prop,
            "level": {"type": "integer"},
            "ability_scores": {
                "type": "object",
                "properties": ability_props,
                "required": list(ability_props.keys()),
            },
            "skills": skills_prop,
            "levels": {
                "type": "object",
                "properties": level_props,
                "required": list(level_props.keys()),
            },
            "equipment": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
        "required": ["class", "ancestry", "heritage", "background", "level",
                      "ability_scores", "skills", "levels", "equipment", "notes"],
    }


def build_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_generation_prompt(
    request: str,
    options: BuildOptions,
    output_format: str = "json",
    ranked_feats: dict[str, list[dict]] | None = None,
) -> str:
    """Build a prompt with decomposed feat options and output template.

    Args:
        request: Free-text build request or flavor text
        options: Decomposed build options from the decomposer
        output_format: "json" or "markdown"
        ranked_feats: Optional ranked feats from vector DB. Dict keyed by
            "{level}_{slot_type}" with list of {"name", "score", "description", "show_description"}.
    """
    parts = []

    # Build request
    parts.append(f"Build request: {request}")
    parts.append("")

    # Feat options per slot — all types now listed (skill feats pre-filtered by prereqs)
    parts.append("=== AVAILABLE FEAT OPTIONS ===")
    parts.append("Your output is schema-constrained — you can ONLY pick feats from the valid lists below.")
    parts.append("Focus on choosing feats that best match the character concept.")
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

            slot_key = f"{level}_{so.slot.slot_type}"

            if so.slot.slot_type == "skill":
                if not skill_feats_printed:
                    _append_grouped_skill_feats(parts, so)
                    skill_feats_printed = True
                else:
                    parts.append(f"  {slot_label} FEAT slot: pick from the skill feat list above (level {level} or lower)")
            elif ranked_feats and slot_key in ranked_feats:
                ranked = ranked_feats[slot_key]
                featured = [r["name"] for r in ranked if r.get("show_description")]
                rest = [r["name"] for r in ranked if not r.get("show_description")]
                parts.append(f"  {slot_label} FEAT slot ({len(so.options)} options, recommended first for this concept):")
                parts.append(f"    ★ {', '.join(featured)}")
                if rest:
                    parts.append(f"    Other: {', '.join(rest)}")
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


_PLAN_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder planning feat selections.

CRITICAL RULES:
- Each feat can only be taken ONCE unless explicitly repeatable.
- Dedication feats require: take at least 2 non-dedication archetype feats from an archetype before taking a second Dedication.
- Feat prerequisites must be satisfied at the level the feat is taken.
- Choose feats that synergize with each other and match the build concept.
- Consider prerequisite chains: picking a feat now may unlock powerful options later.

Output ONLY the feat selections as JSON. No ability scores, skills, or equipment — just feats."""


def build_plan_schema(options: BuildOptions) -> dict:
    """Build a lightweight schema for the feat planning pass — feats only."""
    slots_by_level: dict[int, list[SlotOptions]] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    level_props = {}
    for level in sorted(slots_by_level):
        slot_props = {}
        slot_required = []
        for so in slots_by_level[level]:
            key = f"{so.slot.slot_type}_feat"
            feat_names = sorted(set(o.name for o in so.options))
            slot_props[key] = {"type": "string", "enum": feat_names}
            slot_required.append(key)
        level_props[str(level)] = {
            "type": "object",
            "properties": slot_props,
            "required": slot_required,
        }

    return {
        "type": "object",
        "properties": {
            "levels": {
                "type": "object",
                "properties": level_props,
                "required": list(level_props.keys()),
            },
        },
        "required": ["levels"],
    }


def _build_feat_options_block(
    options: BuildOptions,
    ranked_feats: dict[str, list[dict]] | None = None,
    annotate_prereqs: bool = False,
    starting_skills: list[str] | None = None,
    starting_ability_scores: dict[str, int] | None = None,
) -> list[str]:
    """Build the feat options listing, shared by plan and generation prompts.

    When annotate_prereqs=True, marks each feat with a check/cross based on
    whether its prerequisites are met by the character's starting state.
    """
    parts = []
    parts.append("=== AVAILABLE FEAT OPTIONS PER SLOT ===")
    parts.append("")

    slots_by_level: dict[int, list] = {}
    for so in options.slot_options:
        slots_by_level.setdefault(so.slot.level, []).append(so)

    skill_feats_printed = False
    for level in sorted(slots_by_level):
        parts.append(f"--- Level {level} ---")
        for so in slots_by_level[level]:
            slot_label = so.slot.slot_type.upper()
            slot_key = f"{level}_{so.slot.slot_type}"

            if so.slot.slot_type == "skill":
                if not skill_feats_printed:
                    _append_grouped_skill_feats(parts, so)
                    skill_feats_printed = True
                else:
                    parts.append(f"  {slot_label} FEAT: pick from skill feat list above")
            elif ranked_feats and slot_key in ranked_feats:
                ranked = ranked_feats[slot_key]
                featured = [r["name"] for r in ranked if r.get("show_description")]
                rest = [r["name"] for r in ranked if not r.get("show_description")]
                parts.append(f"  {slot_label} FEAT ({len(so.options)} options, recommended first):")
                parts.append(f"    ★ {', '.join(featured)}")
                if rest:
                    parts.append(f"    Other: {', '.join(rest)}")
            elif len(so.options) > 30:
                parts.append(f"  {slot_label} FEAT ({len(so.options)} options):")
                parts.append(f"    {', '.join(o.name for o in so.options)}")
            else:
                parts.append(f"  {slot_label} FEAT ({len(so.options)} options):")
                for opt in so.options:
                    if annotate_prereqs and opt.prerequisites:
                        mark = _check_prereq_against_starting_state(
                            opt.prerequisites, starting_skills, starting_ability_scores,
                        )
                        line = f"    {mark} {opt.name} (lvl {opt.level}) [prereq: {opt.prerequisites}]"
                    else:
                        line = f"    - {opt.name}"
                        if opt.prerequisites:
                            line += f" [prereq: {opt.prerequisites}]"
                    if opt.rarity != "common":
                        line += f" [{opt.rarity}]"
                    parts.append(line)
        parts.append("")

    return parts


def _check_prereq_against_starting_state(
    prereq_text: str,
    starting_skills: list[str] | None,
    starting_ability_scores: dict[str, int] | None,
) -> str:
    """Check a prerequisite string against starting state. Returns a mark."""
    prereq_lower = prereq_text.lower()
    skills = [s.lower() for s in (starting_skills or [])]
    scores = starting_ability_scores or {}

    for keyword in ["trained in ", "expert in ", "master in "]:
        if keyword in prereq_lower:
            skill_name = prereq_lower.split(keyword, 1)[1].split(",")[0].split(";")[0].strip()
            if skill_name not in skills:
                return "[!]"
            return "[ok]"

    for ability in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        if ability in prereq_lower:
            return "[-]"

    return "[ok]"


_PLAN_STATIC_PREFIX = """\
Select ONE feat for each slot below. Output ONLY the feat names as JSON.
Consider synergies across all levels — your choices should build toward a coherent strategy.
"""


def build_plan_prompt(
    request: str,
    options: BuildOptions,
    ranked_feats: dict[str, list[dict]] | None = None,
    scratchpad_mode: str = "none",
    starting_skills: list[str] | None = None,
    starting_ability_scores: dict[str, int] | None = None,
) -> str:
    """Build prompt for the feat planning pass — feats only, no build details.

    Prompt structure: [static prefix] + [feat options] + [dynamic suffix]
    for KV cache reuse across builds with same class/level.

    scratchpad_mode: "none" (baseline), "reminder" (variant b), "annotated" (variant c)
    """
    parts = []

    # --- Static prefix (cacheable across same-class builds) ---
    parts.append(_PLAN_STATIC_PREFIX)

    # Feat options (static for same class/level/ancestry combo)
    annotate = scratchpad_mode == "annotated"
    parts.extend(_build_feat_options_block(
        options, ranked_feats,
        annotate_prereqs=annotate,
        starting_skills=starting_skills,
        starting_ability_scores=starting_ability_scores,
    ))

    # --- Dynamic suffix (per-build) ---
    parts.append(f"Build concept: {request}")
    parts.append(f"Class: {options.spec.class_name.title()}")
    if options.spec.ancestry_name:
        parts.append(f"Ancestry: {options.spec.ancestry_name.title()}")
    parts.append(f"Level: {options.spec.character_level}")
    parts.append("")

    if options.spec.dedications:
        ded_names = ", ".join(f"{d.title()} Dedication" for d in options.spec.dedications)
        parts.append(f"REQUIRED DEDICATIONS: This build MUST include: {ded_names}.")
        parts.append("Take each Dedication feat at the earliest eligible class feat slot.")
        parts.append("Then take at least 2 non-dedication archetype feats from each before adding another Dedication.")
        parts.append("")

    # --- Scratchpad (end of prompt for maximum recency bias) ---
    if scratchpad_mode in ("reminder", "annotated"):
        parts.append("=== BUILD STATE TRACKING ===")
        parts.append("As you select feats, carefully track:")
        parts.append("- Which feats you have already selected — NEVER pick the same feat twice")
        parts.append("- Which skills your selected feats will require — you must ensure these are trainable")
        parts.append("- Dedication rule: you need 2+ non-dedication archetype feats from a dedication before taking another Dedication feat")
        parts.append("- Fill ALL feat slots — do not leave any empty")
        parts.append("")

    return "\n".join(parts)


def build_guided_schema(
    options: BuildOptions,
    planned_feats: dict,
    required_skills: dict[str, str] | None = None,
) -> dict:
    """Build full response schema with feat slots locked to planned choices.

    Each feat slot becomes a single-value enum — the model can only pick the
    planned feat. Required skills from feat prereqs are enforced as required
    schema fields with minimum proficiency enums.
    """
    schema = build_response_schema(options)

    # Lock feat slots to planned choices
    levels_props = schema.get("properties", {}).get("levels", {}).get("properties", {})
    for level_str, level_schema in levels_props.items():
        planned_level = planned_feats.get(level_str, {})
        for slot_key, slot_schema in level_schema.get("properties", {}).items():
            if slot_key in planned_level and planned_level[slot_key]:
                slot_schema["enum"] = [planned_level[slot_key]]

    # Enforce required skills from feat prerequisites
    if required_skills:
        _RANK_AT_LEAST = {
            "trained": ["trained", "expert", "master", "legendary"],
            "expert": ["expert", "master", "legendary"],
            "master": ["master", "legendary"],
            "legendary": ["legendary"],
        }
        skill_props = {}
        for skill_name, min_rank in required_skills.items():
            allowed = _RANK_AT_LEAST.get(min_rank, ["trained", "expert", "master", "legendary"])
            skill_props[skill_name] = {"type": "string", "enum": allowed}

        schema["properties"]["skills"] = {
            "type": "object",
            "properties": skill_props,
            "required": list(skill_props.keys()),
            "additionalProperties": {
                "type": "string",
                "enum": ["trained", "expert", "master", "legendary"],
            },
        }

    return schema


def build_guided_prompt(
    request: str,
    options: BuildOptions,
    planned_feats: dict,
    constraints: list[str] | None = None,
) -> str:
    """Build prompt for guided generation — feats pre-decided, fill in details."""
    parts = []
    parts.append(f"Build request: {request}")
    parts.append("")
    parts.append("=== FEAT PLAN (these choices are final — do not change them) ===")

    for level_str in sorted(planned_feats, key=lambda x: int(x)):
        slots = planned_feats[level_str]
        picks = [f"{k.replace('_feat', '')}: {v}" for k, v in slots.items() if v]
        parts.append(f"  Level {level_str}: {', '.join(picks)}")

    parts.append("")
    parts.append("Now generate the complete build. The feat choices above are LOCKED.")
    parts.append("Focus on choosing ability scores, skills, heritage, background, and equipment that SUPPORT these feats.")
    parts.append("")

    if constraints:
        parts.append("=== REQUIREMENTS FROM FEAT CHOICES ===")
        for c in constraints:
            parts.append(f"  - {c}")
        parts.append("")

    parts.append("IMPORTANT:")
    parts.append("- Ability scores: base 10 + boosts of 2 (or +1 if score is 18+). Odd scores like 19, 21 are valid at higher levels.")
    parts.append("- Skills should include any skills required by your feat prerequisites")
    parts.append("- Heritage must be a real heritage for your ancestry")
    parts.append("")

    return "\n".join(parts)


def narrow_skill_feat_enums(
    schema: dict,
    trained_skills: list[str],
    character_level: int,
) -> dict:
    """Return a copy of the response schema with skill_feat enums narrowed.

    Replaces the broad skill_feat enum at each level with only feats
    whose 'trained in X' prerequisites are met by the given skills.
    """
    narrowed = copy.deepcopy(schema)
    levels_props = narrowed.get("properties", {}).get("levels", {}).get("properties", {})
    for level_str, level_schema in levels_props.items():
        slot_props = level_schema.get("properties", {})
        if "skill_feat" in slot_props and "enum" in slot_props["skill_feat"]:
            level_num = int(level_str)
            level_eligible = list_skill_feats_for_skills(trained_skills, level_num)
            level_names = sorted(set(f.name for f in level_eligible))
            if level_names:
                slot_props["skill_feat"]["enum"] = level_names
    return narrowed


# ---------------------------------------------------------------------------
# Progressive generation: per-slot prompts and schemas
# ---------------------------------------------------------------------------

_PRIORITY_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. Given a build concept, \
choose ability score priorities and skill training priorities.

Output ONLY valid JSON matching the schema provided."""


def build_priority_prompt(
    request: str,
    class_name: str,
    ancestry_name: str,
    character_level: int,
    class_key_abilities: list[str],
    free_skill_slots: int,
    class_fixed_skills: list[str],
    dedication_requirements: list[str] | None = None,
    available_backgrounds: list[str] | None = None,
    available_heritages: list[str] | None = None,
) -> str:
    """Build prompt for the upfront priority LLM call."""
    parts = []

    if available_backgrounds or available_heritages:
        parts.append("If the build concept names a specific PF2e background or heritage, "
                     "you MUST choose that exact one. Do not substitute alternatives.")
        parts.append("")

    parts.append(f"Build concept: {request}")
    parts.append(f"Class: {class_name.title()} (key ability: {' or '.join(a.upper() for a in class_key_abilities)})")
    parts.append(f"Ancestry: {ancestry_name.title()}, Level: {character_level}")
    parts.append("")

    parts.append("ABILITY PRIORITY: Rank all 6 abilities from most to least important.")
    parts.append(f"Key ability ({' or '.join(a.upper() for a in class_key_abilities)}) should usually be first or second.")
    if dedication_requirements:
        parts.append("Dedication requirements that MUST be met:")
        for req in dedication_requirements:
            parts.append(f"  - {req}")
    parts.append("")

    parts.append(f"SKILL PRIORITY: Choose up to {free_skill_slots} skills to train beyond class grants (exact count depends on Intelligence).")
    if class_fixed_skills:
        parts.append(f"Already trained: {', '.join(s.title() for s in class_fixed_skills)}")
    parts.append(f"Available: {', '.join(s.title() for s in _ALL_SKILLS)}")

    if available_backgrounds:
        parts.append("")
        parts.append("BACKGROUND: Choose one that fits the concept and provides useful skills/boosts.")
    if available_heritages:
        parts.append(f"HERITAGE: Choose a heritage for this {ancestry_name.title()}.")

    return "\n".join(parts)


_ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"]


def build_priority_schema(
    free_skill_slots: int,
    available_backgrounds: list[str] | None = None,
    available_heritages: list[str] | None = None,
) -> dict:
    """Schema for the priority call response.

    Only includes background/heritage fields when they need to be picked
    (not pre-specified). Pre-specified values are locked — the LLM isn't
    asked to choose what's already decided.
    """
    props = {
        "ability_priority": {
            "type": "array",
            "items": {"type": "string", "enum": _ABILITY_NAMES},
            "minItems": 6,
            "maxItems": 6,
        },
        "skill_priority": {
            "type": "array",
            "items": {"type": "string", "enum": list(_ALL_SKILLS)},
            "minItems": min(free_skill_slots, len(_ALL_SKILLS)),
            "maxItems": max(free_skill_slots, 1),
        },
    }
    required = ["ability_priority", "skill_priority"]

    if available_backgrounds:
        props["background"] = {"type": "string", "enum": available_backgrounds}
        required.append("background")
    if available_heritages:
        props["heritage"] = {"type": "string", "enum": available_heritages}
        required.append("heritage")

    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


_SLOT_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder selecting one feat at a time.

Choose the BEST option for this slot that:
- Matches the build concept
- Synergizes with feats already chosen
- Considers future feat prerequisites you might want

Output ONLY valid JSON matching the schema provided."""


def build_slot_prompt(
    request: str,
    slot_type: str,
    slot_level: int,
    filtered_candidates: list[str],
    state_summary: str,
) -> str:
    """Build a narrow prompt for a single slot decision."""
    parts = []
    parts.append(f"Build concept: {request}")
    parts.append("")
    parts.append(state_summary)
    parts.append("")
    parts.append(f"=== {slot_type.upper().replace('_', ' ')} at Level {slot_level} ===")
    parts.append(f"Choose ONE from these {len(filtered_candidates)} options:")
    for name in filtered_candidates:
        parts.append(f"  - {name}")
    return "\n".join(parts)


def build_slot_schema(filtered_candidates: list[str]) -> dict:
    """Schema for a single slot decision — one enum field."""
    return {
        "type": "object",
        "properties": {
            "choice": {"type": "string", "enum": filtered_candidates},
        },
        "required": ["choice"],
    }


def build_skill_increase_prompt(
    request: str,
    slot_level: int,
    eligible_skills: list[str],
    state_summary: str,
) -> str:
    """Build prompt for a skill increase slot."""
    parts = []
    parts.append(f"Build concept: {request}")
    parts.append("")
    parts.append(state_summary)
    parts.append("")
    parts.append(f"=== SKILL INCREASE at Level {slot_level} ===")
    parts.append("Choose ONE skill to increase in proficiency rank:")
    for name in eligible_skills:
        parts.append(f"  - {name}")
    parts.append("")
    parts.append("Prioritize skills needed for feat prerequisites, then skills that match the build concept.")
    return "\n".join(parts)


def build_state_summary(state) -> str:
    """Build a human-readable summary of current character state for slot prompts."""
    parts = []
    parts.append("=== CURRENT BUILD STATE ===")
    parts.append(f"Class: {state.class_name.title()}, Ancestry: {state.ancestry_name.title()}, Level: {state.character_level}")

    if state.feats_chosen:
        by_level: dict[int, list[str]] = {}
        for f in state.feats_chosen:
            by_level.setdefault(f.character_level, []).append(f.name)
        for lvl in sorted(by_level):
            parts.append(f"  L{lvl}: {', '.join(by_level[lvl])}")
    else:
        parts.append("  No feats chosen yet.")

    if state.dedications_taken:
        parts.append(f"Dedications: {', '.join(d.title() for d in state.dedications_taken)}")

    trained = [f"{s.title()} ({r})" for s, r in sorted(state.skills.items()) if r != "untrained"]
    if trained:
        parts.append(f"Skills: {', '.join(trained)}")

    return "\n".join(parts)


_ASSEMBLY_SYSTEM_PROMPT = """\
You are an expert Pathfinder 2nd Edition character builder. Given a complete build \
(class, ancestry, feats, ability scores, skills), choose appropriate starting equipment \
and write a brief build rationale.

Output ONLY valid JSON matching the schema provided."""


def build_assembly_prompt(
    request: str,
    build_summary: str,
) -> str:
    """Build prompt for the final assembly call (equipment + notes)."""
    parts = []
    parts.append(f"Build concept: {request}")
    parts.append("")
    parts.append(build_summary)
    parts.append("")
    parts.append("Choose starting equipment appropriate for this build and write a brief rationale.")
    return "\n".join(parts)


def build_assembly_schema() -> dict:
    """Schema for the assembly call response."""
    return {
        "type": "object",
        "properties": {
            "equipment": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
        "required": ["equipment", "notes"],
    }
