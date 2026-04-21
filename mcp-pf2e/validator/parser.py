"""Parse LLM-generated character build text into structured form."""

import re

from .types import ParsedBuild, ParsedFeatChoice

_SLOT_TYPE_KEYWORDS = {
    "class feat": "class",
    "class": "class",
    "ancestry feat": "ancestry",
    "ancestry": "ancestry",
    "heritage feat": "ancestry",
    "general feat": "general",
    "general": "general",
    "skill feat": "skill",
    "skill": "skill",
    "archetype feat": "archetype",
    "archetype": "archetype",
    "dedication": "archetype",
    "bonus feat": "class",
}

_ABILITY_NAMES = {
    "str": "str", "strength": "str",
    "dex": "dex", "dexterity": "dex",
    "con": "con", "constitution": "con",
    "int": "int", "intelligence": "int",
    "wis": "wis", "wisdom": "wis",
    "cha": "cha", "charisma": "cha",
}

_EXCLUDED_NAMES = {
    "the", "and", "for", "with", "level", "feat", "spell",
    "none", "note", "see", "class", "general", "skill",
    "ancestry", "heritage", "background", "equipment",
    "str", "dex", "con", "int", "wis", "cha",
    "deity", "cause", "key ability", "expert", "master", "trained",
    "legendary", "untrained", "ancestry feats", "class feats",
    "general feats", "skill feats", "archetype feats", "feats",
    "spells", "cantrips", "equipment loadout", "ability scores",
    "starting stats", "combat stats", "skill training",
    "personality", "backstory", "requirements", "special",
    "trigger", "effect",
}


def _clean_name(raw: str) -> str:
    name = raw.strip().rstrip(".,;:!?*")
    name = re.sub(r"\s*\(.*$", "", name)
    if len(name) < 3 or name.lower() in _EXCLUDED_NAMES:
        return ""
    if name[0].islower():
        return ""
    return name


def _detect_slot_type(context: str) -> str:
    """Detect feat slot type from surrounding text context."""
    context_lower = context.lower()
    for keyword, slot_type in _SLOT_TYPE_KEYWORDS.items():
        if keyword in context_lower:
            return slot_type
    return ""


def _extract_level(context: str) -> int:
    """Extract character level from surrounding text."""
    m = re.search(r"level\s+(\d+)", context, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def parse_build(
    text: str,
    expected_class: str = "",
    expected_ancestry: str = "",
    expected_level: int = 0,
) -> ParsedBuild:
    """Parse LLM-generated character build text into structured form."""
    build = ParsedBuild(
        class_name=expected_class,
        ancestry_name=expected_ancestry,
        character_level=expected_level,
        raw_text=text,
    )

    # Try to extract class/ancestry/level from text if not provided
    if not build.class_name:
        build.class_name = _extract_field(text, ["class"])
    if not build.ancestry_name:
        build.ancestry_name = _extract_field(text, ["ancestry", "race"])
    if not build.character_level:
        m = re.search(r"level\s+(\d+)", text, re.IGNORECASE)
        if m:
            build.character_level = int(m.group(1))

    build.heritage = _extract_field(text, ["heritage"])
    build.background = _extract_field(text, ["background"])
    build.ability_scores = _extract_ability_scores(text)
    build.feats = _extract_feats(text)

    return build


def _extract_field(text: str, labels: list[str]) -> str:
    """Extract a named field value from text."""
    for label in labels:
        pattern = rf"\*{{0,2}}{label}\*{{0,2}}\s*[:—]\s*\*{{0,2}}([A-Z][A-Za-z\'\-\s]+?)[\*\n,.(]"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return _clean_name(m.group(1))
    return ""


def _extract_ability_scores(text: str) -> dict[str, int]:
    """Extract ability scores from text."""
    scores = {}
    for full_name, short in _ABILITY_NAMES.items():
        if short in scores:
            continue
        pattern = rf"\b{full_name}\b\s*[:=]?\s*(\d{{1,2}})"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            scores[short] = int(m.group(1))
    return scores


def _extract_feats(text: str) -> list[ParsedFeatChoice]:
    """Extract feat choices with slot type and level context."""
    feats = []
    seen = set()

    current_section_type = ""
    current_section_level = 0

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Strip markdown bold for easier pattern matching
        plain = stripped.replace("**", "")

        # Detect section headers like "## Class Feats" or "### Ancestry Feats"
        header_match = re.match(r"#{1,4}\s+(.+)", stripped)
        if header_match:
            header_text = header_match.group(1)
            current_section_type = _detect_slot_type(header_text)
            lvl = _extract_level(header_text)
            if lvl:
                current_section_level = lvl
            continue

        # Pattern: "Level N Slot Type: Name" or "Slot Type: Name"
        label_match = re.match(
            r"[-•*]*\s*(?:level\s+(\d+)\s+)?"
            r"((?:class|ancestry|general|skill|archetype|bonus)\s+feat|heritage|dedication|feat)"
            r"\s*[:—]\s*([A-Z][A-Za-z\'\-\s]+)",
            plain,
            re.IGNORECASE,
        )
        if label_match:
            lvl = int(label_match.group(1)) if label_match.group(1) else 0
            slot_type = _detect_slot_type(label_match.group(2))
            name = _clean_name(label_match.group(3))
            if name and name not in seen:
                seen.add(name)
                feats.append(ParsedFeatChoice(
                    name=name,
                    slot_type=slot_type or current_section_type,
                    character_level=lvl or current_section_level,
                ))
            continue

        # Pattern: "Level N: Name (type)"
        level_match = re.match(
            r"[-•*]*\s*Level\s+(\d+)\s*[:—]\s*([A-Z][A-Za-z\'\-\s]+?)\s*[.,(]",
            plain,
            re.IGNORECASE,
        )
        if level_match:
            lvl = int(level_match.group(1))
            name = _clean_name(level_match.group(2))
            slot_type = _detect_slot_type(plain)
            if name and name not in seen:
                seen.add(name)
                feats.append(ParsedFeatChoice(
                    name=name,
                    slot_type=slot_type or current_section_type,
                    character_level=lvl,
                ))
            continue

        # Pattern: "- Name (description)" bullet points
        bullet_match = re.match(
            r"[-•*]\s+([A-Z][A-Za-z\'\-\s]{2,}?)[\s.,;:(]",
            plain,
        )
        if bullet_match:
            name = _clean_name(bullet_match.group(1))
            lvl = _extract_level(plain)
            if name and name not in seen:
                seen.add(name)
                feats.append(ParsedFeatChoice(
                    name=name,
                    slot_type=_detect_slot_type(plain) or current_section_type,
                    character_level=lvl or current_section_level,
                ))
            continue

        # Pattern: "- Name (level X type feat)"
        paren_match = re.match(
            r"[-•*]\s+([A-Z][A-Za-z\'\-\s]{2,}?)\s*\((.+?)\)",
            plain,
        )
        if paren_match:
            name = _clean_name(paren_match.group(1))
            context = paren_match.group(2)
            slot_type = _detect_slot_type(context)
            lvl = _extract_level(context)
            if name and name not in seen:
                seen.add(name)
                feats.append(ParsedFeatChoice(
                    name=name,
                    slot_type=slot_type or current_section_type,
                    character_level=lvl or current_section_level,
                ))
            continue

        # Pattern: table row "| Name | Type | Level |"
        table_match = re.match(r"\|\s*([A-Z][A-Za-z\'\-\s]{2,}?)\s*\|(.+)\|", plain)
        if table_match:
            name = _clean_name(table_match.group(1))
            context = table_match.group(2)
            if name and name not in seen and len(name.split()) <= 5:
                seen.add(name)
                feats.append(ParsedFeatChoice(
                    name=name,
                    slot_type=_detect_slot_type(context) or current_section_type,
                    character_level=_extract_level(context) or current_section_level,
                ))

    return feats
