"""Individual validation rules for PF2e character builds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ValidationError
from query.static_reader import get_class_data, get_feat_slot_levels

# Optional: PF2eDB for database-backed feat verification
try:
    from server.db import PF2eDB
except ImportError:
    PF2eDB = None


def check_feat_existence(
    build: ParsedBuild,
    db: "PF2eDB | None" = None,
) -> list[ValidationError]:
    """Verify every named feat exists in the database."""
    errors = []
    verified = []

    if db is None:
        return errors

    for feat in build.feats:
        entry = db.get_entry(feat.name, content_type=None)
        if entry:
            verified.append(feat.name)
        else:
            # Try fuzzy search
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
            else:
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
                severity="warning",
                message=f"Missing {slot_type} feats: {act} taken but {exp} slots available at level {build.character_level}.",
                details={"slot_type": slot_type, "expected": exp, "actual": act},
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
