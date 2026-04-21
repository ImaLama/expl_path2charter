"""Individual validation rules for PF2e character builds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ValidationError
from .prerequisite import parse_prerequisites, check_prerequisite
from query.static_reader import (
    get_class_data, get_feat_slot_levels,
    list_heritages, list_backgrounds, _fuzzy_match,
)

# Optional: PF2eDB for database-backed feat verification
try:
    from server.db import PF2eDB
except ImportError:
    PF2eDB = None


def check_feat_existence(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
    skip_semantic: bool = False,
) -> list[ValidationError]:
    """Verify every named feat exists in the database.

    get_entry() does exact name lookup (no embedding needed).
    Semantic search fallback (needs mxbai loaded) is skipped when skip_semantic=True.
    """
    errors = []

    if db is None:
        return errors

    for feat in build.feats:
        entry = db.get_entry(feat.name, content_type=None)
        if entry:
            continue

        if not skip_semantic:
            results = db.search(query=feat.name, n_results=1)
            if results and results[0]["relevance_score"] > 0.85:
                suggestion = results[0]["name"]
                errors.append(ValidationError(
                    rule="feat_existence",
                    severity="error",
                    message=f'"{feat.name}" not found. Did you mean "{suggestion}"?',
                    feat_name=feat.name,
                    details={"suggestion": suggestion, "score": results[0]["relevance_score"]},
                ))
                continue

        errors.append(ValidationError(
            rule="feat_existence",
            severity="error",
            message=f'"{feat.name}" is not a known PF2e feat, spell, or feature.',
            feat_name=feat.name,
        ))

    return errors


def check_level_legality(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Each feat's level must be <= the character level at which it's taken."""
    errors = []

    if db is None or build.character_level == 0:
        return errors

    for feat in build.feats:
        entry = db.get_entry(feat.name, content_type=None)
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


def check_feat_slot_type(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Verify feats are in the correct slot type (skill feats in skill slots, etc.)."""
    errors = []

    if db is None:
        return errors

    for feat in build.feats:
        if not feat.slot_type or feat.slot_type == "archetype":
            continue

        valid_categories = _SLOT_TO_VALID_CATEGORIES.get(feat.slot_type)
        if not valid_categories:
            continue

        entry = db.get_entry(feat.name, content_type=None)
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


def check_class_feat_access(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Class feats must have the character's class in their traits."""
    errors = []

    if db is None or not build.class_name:
        return errors

    class_slug = build.class_name.lower()

    for feat in build.feats:
        if feat.slot_type != "class":
            continue

        entry = db.get_entry(feat.name, content_type=None)
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


def check_prerequisites(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Check that each feat's prerequisites are satisfied."""
    errors = []

    if db is None:
        return errors

    for feat in build.feats:
        entry = db.get_entry(feat.name, content_type=None)
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


def check_archetype_rules(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Check PF2e archetype dedication rules.

    - Must take a dedication feat before any other archetype feats from that archetype
    - Can't take a second dedication until you have 2 non-dedication feats from the first
    """
    errors = []

    if db is None:
        return errors

    dedications = []
    archetype_feats = []

    for feat in build.feats:
        entry = db.get_entry(feat.name, content_type=None)
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


def check_ancestry_feat_access(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Ancestry feats must belong to the character's ancestry."""
    errors = []

    if db is None or not build.ancestry_name:
        return errors

    ancestry_slug = build.ancestry_name.lower()

    for feat in build.feats:
        if feat.slot_type != "ancestry":
            continue

        entry = db.get_entry(feat.name, content_type=None)
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
