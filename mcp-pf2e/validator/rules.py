"""Individual validation rules for PF2e character builds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ValidationError
from .prerequisite import parse_prerequisites, check_prerequisite
from query.static_reader import (
    get_class_data, get_feat_slot_levels,
    get_class_trained_skills, get_background_data, get_ancestry_data,
    list_heritages, list_backgrounds, _fuzzy_match, get_feat_data,
)


_REPEATABLE_FEATS = {"additional lore", "assurance", "skill training"}


def check_duplicate_feats(build: ParsedBuild) -> list[ValidationError]:
    """Most PF2e feats can only be taken once."""
    errors = []
    seen: dict[str, int] = {}
    for feat in build.feats:
        name_lower = feat.name.lower()
        if name_lower in _REPEATABLE_FEATS:
            continue
        if name_lower in seen:
            errors.append(ValidationError(
                rule="duplicate_feat",
                severity="error",
                message=f'"{feat.name}" is taken more than once. Most feats can only be taken once.',
                feat_name=feat.name,
            ))
        seen[name_lower] = seen.get(name_lower, 0) + 1
    return errors


def check_feat_existence(build: ParsedBuild) -> list[ValidationError]:
    """Verify every named feat exists in the static data."""
    errors = []

    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if entry:
            rarity = entry.get("system", {}).get("traits", {}).get("rarity", "common")
            if rarity in ("uncommon", "rare", "unique"):
                errors.append(ValidationError(
                    rule="rarity",
                    severity="warning",
                    message=f'"{feat.name}" is {rarity} — typically requires GM permission.',
                    feat_name=feat.name,
                    details={"rarity": rarity},
                ))
            continue

        errors.append(ValidationError(
            rule="feat_existence",
            severity="error",
            message=f'"{feat.name}" is not a known PF2e feat, spell, or feature.',
            feat_name=feat.name,
        ))

    return errors


def check_level_legality(build: ParsedBuild) -> list[ValidationError]:
    """Each feat's level must be <= the character level at which it's taken."""
    errors = []

    if build.character_level == 0:
        return errors

    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue

        feat_level_raw = entry.get("system", {}).get("level", {})
        if isinstance(feat_level_raw, dict):
            feat_level = feat_level_raw.get("value", 0)
        else:
            feat_level = feat_level_raw or 0
        feat_level = int(feat_level)

        # Check against the slot level if known, otherwise against character level
        check_level = feat.character_level if feat.character_level > 0 else build.character_level

        if feat_level > check_level:
            errors.append(ValidationError(
                rule="level_legality",
                severity="error",
                message=f'"{feat.name}" is level {feat_level} but taken at character level {check_level}.',
                feat_name=feat.name,
                details={"feat_level": feat_level, "character_level": check_level},
            ))

    return errors


def check_slot_counts(
    build: ParsedBuild,
) -> list[ValidationError]:
    """Verify correct number of feats per slot type for the character level."""
    errors = []

    if not build.class_name or build.character_level == 0:
        return errors

    slot_levels = get_feat_slot_levels(build.class_name)
    if not slot_levels["class"]:
        errors.append(ValidationError(
            rule="slot_counts",
            severity="warning",
            message=f'Could not load class data for "{build.class_name}" to verify slot counts.',
        ))
        return errors

    # Count expected slots at or below character level
    expected = {}
    for slot_type, levels in slot_levels.items():
        expected[slot_type] = sum(1 for lvl in levels if lvl <= build.character_level)

    # Count actual feats by slot type
    actual = {"class": 0, "ancestry": 0, "general": 0, "skill": 0}
    untyped = 0
    for feat in build.feats:
        if feat.slot_type in actual:
            actual[feat.slot_type] += 1
        elif feat.slot_type == "archetype":
            actual["class"] += 1  # Archetype feats use class feat slots
        else:
            untyped += 1

    for slot_type in ["class", "ancestry", "general", "skill"]:
        exp = expected.get(slot_type, 0)
        act = actual.get(slot_type, 0)
        if act > exp:
            errors.append(ValidationError(
                rule="slot_counts",
                severity="error",
                message=f"Too many {slot_type} feats: {act} taken but only {exp} slots available at level {build.character_level}.",
                details={"slot_type": slot_type, "expected": exp, "actual": act},
            ))
        elif act < exp and untyped == 0:
            errors.append(ValidationError(
                rule="slot_counts",
                severity="error",
                message=f"Missing {slot_type} feats: {act} taken but {exp} slots available at level {build.character_level}.",
                details={"slot_type": slot_type, "expected": exp, "actual": act},
            ))

    return errors


_SLOT_TO_VALID_CATEGORIES = {
    "skill": {"skill"},
    "general": {"general"},
    "ancestry": {"ancestry"},
    "class": {"class", "classfeature"},
}


def check_feat_slot_type(build: ParsedBuild) -> list[ValidationError]:
    """Verify feats are in the correct slot type (skill feats in skill slots, etc.)."""
    errors = []

    for feat in build.feats:
        if not feat.slot_type or feat.slot_type == "archetype":
            continue

        valid_categories = _SLOT_TO_VALID_CATEGORIES.get(feat.slot_type)
        if not valid_categories:
            continue

        entry = get_feat_data(feat.name)
        if not entry:
            continue

        category = (entry.get("system", {}).get("category", "") or "").lower()
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]

        # Class feats can also be archetype feats
        if feat.slot_type == "class" and "archetype" in traits_lower:
            continue

        if category and category not in valid_categories:
            errors.append(ValidationError(
                rule="feat_slot_type",
                severity="error",
                message=f'"{feat.name}" is a {category} feat, not a {feat.slot_type} feat.',
                feat_name=feat.name,
                details={"category": category, "slot_type": feat.slot_type},
            ))

    return errors


def check_class_feat_access(build: ParsedBuild) -> list[ValidationError]:
    """Class feats must have the character's class in their traits."""
    errors = []

    if not build.class_name:
        return errors

    class_slug = build.class_name.lower()

    for feat in build.feats:
        if feat.slot_type != "class":
            continue

        entry = get_feat_data(feat.name)
        if not entry:
            continue

        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]

        # Class feats must have the class in traits, OR be archetype feats
        if class_slug not in traits_lower and "archetype" not in traits_lower:
            errors.append(ValidationError(
                rule="class_feat_access",
                severity="error",
                message=f'"{feat.name}" is not available to {build.class_name} (traits: {traits}).',
                feat_name=feat.name,
                details={"traits": traits, "class": build.class_name},
            ))

    return errors


def check_prerequisites(build: ParsedBuild) -> list[ValidationError]:
    """Check that each feat's prerequisites are satisfied."""
    errors = []

    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue

        prereqs_raw = entry.get("system", {}).get("prerequisites", {}).get("value", [])
        prereq_parts = []
        for p in prereqs_raw:
            if isinstance(p, dict):
                prereq_parts.append(p.get("value", ""))
            elif isinstance(p, str):
                prereq_parts.append(p)
        prereq_string = "; ".join(p for p in prereq_parts if p)

        if not prereq_string:
            continue

        parsed = parse_prerequisites(prereq_string)
        for prereq in parsed:
            satisfied, reason = check_prerequisite(prereq, build)
            if not satisfied:
                errors.append(ValidationError(
                    rule="prerequisite",
                    severity="error",
                    message=f'"{feat.name}" {reason}.',
                    feat_name=feat.name,
                    details={"prerequisite": prereq.raw, "type": prereq.type},
                ))

    return errors


def check_archetype_rules(build: ParsedBuild) -> list[ValidationError]:
    """Check PF2e archetype dedication rules.

    - Must take a dedication feat before any other archetype feats from that archetype
    - Can't take a second dedication until you have 2 non-dedication feats from the first
    """
    errors = []

    dedications = []
    archetype_feats = []

    for feat in build.feats:
        entry = get_feat_data(feat.name)
        if not entry:
            continue
        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]

        if "dedication" in traits_lower:
            dedications.append(feat.name)
        elif "archetype" in traits_lower:
            archetype_feats.append(feat.name)

    # Can't take 2nd dedication without 2 non-dedication archetype feats from the 1st
    if len(dedications) >= 2 and len(archetype_feats) < 2:
        errors.append(ValidationError(
            rule="archetype_rules",
            severity="error",
            message=f"Second dedication ({dedications[1]}) requires at least 2 non-dedication archetype feats from the first ({dedications[0]}).",
            details={"dedications": dedications, "archetype_feats": archetype_feats},
        ))

    return errors


def check_ancestry_feat_access(build: ParsedBuild) -> list[ValidationError]:
    """Ancestry feats must belong to the character's ancestry."""
    errors = []

    if not build.ancestry_name:
        return errors

    ancestry_slug = build.ancestry_name.lower()

    for feat in build.feats:
        if feat.slot_type != "ancestry":
            continue

        entry = get_feat_data(feat.name)
        if not entry:
            continue

        traits = entry.get("system", {}).get("traits", {}).get("value", [])
        traits_lower = [t.lower() for t in traits]

        if ancestry_slug not in traits_lower:
            errors.append(ValidationError(
                rule="ancestry_feat_access",
                severity="error",
                message=f'"{feat.name}" is not a {build.ancestry_name} ancestry feat (traits: {traits}).',
                feat_name=feat.name,
                details={"traits": traits, "ancestry": build.ancestry_name},
            ))

    return errors


def check_heritage(build: ParsedBuild) -> list[ValidationError]:
    """Verify heritage exists and belongs to the chosen ancestry."""
    errors = []

    if not build.heritage or not build.ancestry_name:
        return errors

    available = list_heritages(build.ancestry_name)
    if not available:
        return errors

    match = _fuzzy_match(build.heritage, available)
    if not match:
        suggestions = [h for h in available if build.ancestry_name.lower() in h.lower()][:3]
        if not suggestions:
            suggestions = available[:5]
        errors.append(ValidationError(
            rule="heritage",
            severity="error",
            message=f'"{build.heritage}" is not a valid {build.ancestry_name} heritage. Options include: {", ".join(suggestions)}.',
            feat_name=build.heritage,
            details={"available": available},
        ))

    return errors


def check_background(build: ParsedBuild) -> list[ValidationError]:
    """Verify background exists."""
    errors = []

    if not build.background:
        return errors

    available = list_backgrounds()
    if not available:
        return errors

    match = _fuzzy_match(build.background, available)
    if not match:
        errors.append(ValidationError(
            rule="background",
            severity="error",
            message=f'"{build.background}" is not a known PF2e background.',
            feat_name=build.background,
        ))

    return errors


_RANK_ORDER = {"untrained": 0, "trained": 1, "expert": 2, "master": 3, "legendary": 4}
_RANK_MIN_LEVEL = {"trained": 1, "expert": 3, "master": 7, "legendary": 15}


def check_skill_ranks(build: ParsedBuild) -> list[ValidationError]:
    """Verify skill ranks don't exceed what's achievable at the character's level."""
    errors = []

    if not build.skills or build.character_level == 0:
        return errors

    for skill, rank in build.skills.items():
        rank_lower = rank.lower()
        min_level = _RANK_MIN_LEVEL.get(rank_lower, 0)
        if min_level > build.character_level:
            errors.append(ValidationError(
                rule="skill_ranks",
                severity="error",
                message=f'"{skill}" at {rank} requires level {min_level}+, but character is level {build.character_level}.',
                details={"skill": skill, "rank": rank, "min_level": min_level},
            ))

    return errors


def check_skill_counts(build: ParsedBuild) -> list[ValidationError]:
    """Verify the total number of trained skills is plausible."""
    errors = []

    if not build.skills or not build.class_name or build.character_level == 0:
        return errors

    # Count trained-or-better skills
    trained_count = sum(1 for rank in build.skills.values() if _RANK_ORDER.get(rank.lower(), 0) >= 1)

    # Calculate expected sources of skill training
    skill_info = get_class_trained_skills(build.class_name)
    class_fixed = len(skill_info.get("fixed", []))
    class_additional = skill_info.get("additional", 0)
    class_custom = 1 if skill_info.get("custom") else 0

    # Background grants 1-2 skills
    bg_skills = 0
    if build.background:
        bg_data = get_background_data(build.background)
        if bg_data:
            bg_ts = bg_data.get("system", {}).get("trainedSkills", {})
            bg_skills = len(bg_ts.get("value", [])) + len(bg_ts.get("lore", []))

    # Int modifier grants additional skills at level 1
    int_score = build.ability_scores.get("int", 10)
    int_modifier = max(0, (int_score - 10) // 2)

    base_trained = class_fixed + class_additional + class_custom + bg_skills + int_modifier

    # Skill increases at higher levels (from class data)
    class_data = get_class_data(build.class_name)
    increase_levels = []
    if class_data:
        increase_levels = class_data.get("system", {}).get("skillIncreaseLevels", {}).get("value", [])
    increases = sum(1 for lvl in increase_levels if lvl <= build.character_level)

    max_possible = base_trained + increases

    if trained_count > max_possible + 2:
        errors.append(ValidationError(
            rule="skill_counts",
            severity="warning",
            message=f"Character has {trained_count} trained skills but at most ~{max_possible} are expected at level {build.character_level}.",
            details={"trained": trained_count, "max_expected": max_possible},
        ))

    return errors


def check_ability_scores(build: ParsedBuild) -> list[ValidationError]:
    """Bounds-check ability scores — catch common LLM errors without exact verification.

    Checks: odd scores, scores above maximum achievable, key ability too low,
    scores below 8 without explanation. Does NOT try to verify exact boost choices.
    """
    errors = []

    if not build.ability_scores or build.character_level == 0:
        return errors

    # Calculate maximum achievable at this level
    # Level 1: base 10 + up to ~7 boosts possible (2 ancestry + 1 background + 1 class + 4 free - 1 flaw)
    # Each boost below 18 adds +2, above 18 adds +1
    # Level 5/10/15/20 each add 4 more boosts
    level_boost_rounds = sum(1 for lvl in [5, 10, 15, 20] if lvl <= build.character_level)
    # Theoretical max: 18 at level 1 + level_boost_rounds * 1 (above 18, boosts add +1)
    # Realistic max at level 1: 18 (very focused), level 5: 19, level 10: 20, level 20: 22+
    max_at_level = 18 + level_boost_rounds

    # Get key ability for the class
    key_abilities = []
    class_data = get_class_data(build.class_name)
    if class_data:
        key_abilities = class_data.get("system", {}).get("keyAbility", {}).get("value", [])

    for ability, score in build.ability_scores.items():
        if not isinstance(score, int):
            continue

        # Odd scores are impossible (base 10 + even boosts)
        if score % 2 != 0:
            errors.append(ValidationError(
                rule="ability_scores",
                severity="error",
                message=f"{ability.upper()} {score} is odd — PF2e ability scores are always even (base 10 + boosts of 2).",
                details={"ability": ability, "score": score},
            ))

        # Score above maximum achievable
        if score > max_at_level:
            errors.append(ValidationError(
                rule="ability_scores",
                severity="error",
                message=f"{ability.upper()} {score} exceeds maximum achievable ({max_at_level}) at level {build.character_level}.",
                details={"ability": ability, "score": score, "max": max_at_level},
            ))

        # Score below 8 without ancestry flaw (warning, not error — voluntary flaws exist)
        if score < 8:
            errors.append(ValidationError(
                rule="ability_scores",
                severity="warning",
                message=f"{ability.upper()} {score} is unusually low — verify voluntary flaw or ancestry flaw applies.",
                details={"ability": ability, "score": score},
            ))

    # Key ability should be at least 16 at level 1 (class boost + at least one other boost)
    if key_abilities and build.character_level >= 1:
        for ka in key_abilities:
            ka_score = build.ability_scores.get(ka, 0)
            if ka_score and ka_score < 14:
                errors.append(ValidationError(
                    rule="ability_scores",
                    severity="warning",
                    message=f"Key ability {ka.upper()} is {ka_score} — typically at least 16 at level 1 (class boost + other boosts).",
                    details={"ability": ka, "score": ka_score, "key_ability": True},
                ))
                break  # Only warn once (class may have multiple key ability options)

    return errors
