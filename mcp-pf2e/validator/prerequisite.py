"""Parse and check PF2e prerequisite strings."""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild
from query.static_reader import get_class_features


@dataclass
class Prerequisite:
    """A single parsed prerequisite."""
    type: str       # "feat", "proficiency", "ability_score", "dedication", "other"
    value: str      # Parsed value (feat name, "trained:Acrobatics", "str:14", etc.)
    raw: str        # Original text


_ABILITY_MAP = {
    "strength": "str", "dexterity": "dex", "constitution": "con",
    "intelligence": "int", "wisdom": "wis", "charisma": "cha",
}

_PROFICIENCY_RANKS = {"untrained": 0, "trained": 1, "expert": 2, "master": 3, "legendary": 4}

# Modifier to score: +1=12, +2=14, +3=16, +4=18, +5=20
_MODIFIER_TO_SCORE = {1: 12, 2: 14, 3: 16, 4: 18, 5: 20}


def parse_prerequisites(prereq_string: str) -> list[Prerequisite]:
    """Parse a semicolon-separated prerequisite string into structured form."""
    if not prereq_string:
        return []

    results = []
    parts = [p.strip() for p in prereq_string.split(";")]

    for part in parts:
        if not part:
            continue
        prereq = _parse_single(part)
        results.append(prereq)

    return results


def _parse_single(text: str) -> Prerequisite:
    """Parse a single prerequisite clause."""
    text = text.strip()

    # Proficiency: "trained in Acrobatics", "expert in Athletics", "master in Perception"
    prof_match = re.match(
        r"(trained|expert|master|legendary)\s+in\s+(.+)",
        text, re.IGNORECASE,
    )
    if prof_match:
        rank = prof_match.group(1).lower()
        skill = prof_match.group(2).strip()
        return Prerequisite(type="proficiency", value=f"{rank}:{skill}", raw=text)

    # Ability score with modifier: "Strength +2", "Charisma +3"
    ability_mod_match = re.match(
        r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s*\+(\d+)",
        text, re.IGNORECASE,
    )
    if ability_mod_match:
        ability = _ABILITY_MAP[ability_mod_match.group(1).lower()]
        modifier = int(ability_mod_match.group(2))
        score = _MODIFIER_TO_SCORE.get(modifier, 10 + modifier * 2)
        return Prerequisite(type="ability_score", value=f"{ability}:{score}", raw=text)

    # Ability score with raw number: "Strength 14"
    ability_score_match = re.match(
        r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+(\d+)",
        text, re.IGNORECASE,
    )
    if ability_score_match:
        ability = _ABILITY_MAP[ability_score_match.group(1).lower()]
        score = int(ability_score_match.group(2))
        return Prerequisite(type="ability_score", value=f"{ability}:{score}", raw=text)

    # Dedication reference: contains "Dedication"
    if "dedication" in text.lower():
        return Prerequisite(type="dedication", value=text, raw=text)

    # Feat/feature reference: starts with uppercase, looks like a proper name
    if text and text[0].isupper() and not any(
        kw in text.lower() for kw in ["ability to", "at least", "member of", "access to"]
    ):
        return Prerequisite(type="feat", value=text, raw=text)

    return Prerequisite(type="other", value=text, raw=text)


def check_prerequisite(prereq: Prerequisite, build: ParsedBuild) -> tuple[bool, str]:
    """Check if a prerequisite is satisfied by the build.

    Returns (satisfied, reason).
    """
    if prereq.type == "feat" or prereq.type == "dedication":
        # Check against both chosen feats AND auto-granted class features
        feat_names_lower = {f.name.lower() for f in build.feats}
        if build.class_name:
            class_features = get_class_features(build.class_name, build.character_level)
            feat_names_lower.update(f.lower() for f in class_features)
        if prereq.value.lower() in feat_names_lower:
            return True, ""
        if " or " in prereq.value:
            alternatives = [a.strip() for a in prereq.value.split(" or ")]
            if any(a.lower() in feat_names_lower for a in alternatives):
                return True, ""
            return False, f"requires one of: {prereq.value}"
        return False, f'requires "{prereq.value}" which was not taken'

    if prereq.type == "ability_score":
        parts = prereq.value.split(":")
        if len(parts) == 2:
            ability, required = parts[0], int(parts[1])
            actual = build.ability_scores.get(ability, 0)
            if actual == 0:
                return True, ""  # Can't verify without ability scores
            if actual >= required:
                return True, ""
            return False, f"requires {prereq.raw} but has {ability.upper()} {actual}"

    if prereq.type == "proficiency":
        if not build.skills:
            return True, ""  # Can't verify without skills data
        # Parse "trained:Acrobatics" → rank, skill
        parts = prereq.value.split(":", 1)
        if len(parts) == 2:
            required_rank, skill_name = parts[0].lower(), parts[1].strip().lower()
            actual_rank = build.skills.get(skill_name, "untrained").lower()
            rank_order = {"untrained": 0, "trained": 1, "expert": 2, "master": 3, "legendary": 4}
            if rank_order.get(actual_rank, 0) >= rank_order.get(required_rank, 0):
                return True, ""
            if actual_rank == "untrained":
                return False, f'requires {prereq.raw} but character is untrained in {skill_name.title()}'
            return False, f'requires {prereq.raw} but character is only {actual_rank} in {skill_name.title()}'

    # "other" type — can't verify deterministically
    return True, ""
