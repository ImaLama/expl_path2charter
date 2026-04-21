"""Build validation engine — orchestrates all validation rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ParsedFeatChoice, ValidationResult
from .parser import parse_build
from .rules import (
    check_duplicate_feats,
    check_feat_existence,
    check_level_legality,
    check_slot_counts,
    check_feat_slot_type,
    check_class_feat_access,
    check_ancestry_feat_access,
    check_heritage,
    check_background,
    check_skill_ranks,
    check_skill_counts,
    check_ability_scores,
    check_prerequisites,
    check_archetype_rules,
)

try:
    from server.db import PF2eDB
except ImportError:
    PF2eDB = None


class BuildValidator:
    """Orchestrates all validation rules for a PF2e character build."""

    def __init__(self, db: "PF2eDB | None" = None, skip_semantic: bool = False):
        self._db = db
        self._skip_semantic = skip_semantic

    def _run_rules(self, build: ParsedBuild) -> ValidationResult:
        """Run all validation rules against a parsed build."""
        all_errors = []
        all_errors.extend(check_duplicate_feats(build))
        all_errors.extend(check_feat_existence(build, self._db, skip_semantic=self._skip_semantic))
        all_errors.extend(check_level_legality(build, self._db))
        all_errors.extend(check_slot_counts(build))
        all_errors.extend(check_feat_slot_type(build, self._db))
        all_errors.extend(check_class_feat_access(build, self._db))
        all_errors.extend(check_ancestry_feat_access(build, self._db))
        all_errors.extend(check_heritage(build))
        all_errors.extend(check_background(build))
        all_errors.extend(check_skill_ranks(build))
        all_errors.extend(check_skill_counts(build))
        all_errors.extend(check_ability_scores(build))
        all_errors.extend(check_prerequisites(build, self._db))
        all_errors.extend(check_archetype_rules(build, self._db))

        errors = [e for e in all_errors if e.severity == "error"]
        warnings = [e for e in all_errors if e.severity == "warning"]

        errored_feats = {e.feat_name for e in errors if e.feat_name}
        verified = [f.name for f in build.feats if f.name not in errored_feats]

        return ValidationResult(
            errors=errors,
            warnings=warnings,
            verified_feats=verified,
            build=build,
        )

    def validate(
        self,
        text: str,
        expected_class: str = "",
        expected_ancestry: str = "",
        expected_level: int = 0,
    ) -> ValidationResult:
        """Validate a free-text (markdown) build via regex parsing."""
        build = parse_build(
            text,
            expected_class=expected_class,
            expected_ancestry=expected_ancestry,
            expected_level=expected_level,
        )
        return self._run_rules(build)

    def validate_json(
        self,
        data: dict,
        expected_class: str = "",
        expected_ancestry: str = "",
        expected_level: int = 0,
    ) -> ValidationResult:
        """Validate a JSON build directly — no regex parsing.

        Walks the 'levels' dict structure:
        {"1": {"class_feat": "X", "ancestry_feat": "Y"}, "2": {...}, ...}
        """
        build = ParsedBuild(
            class_name=data.get("class", expected_class).lower(),
            ancestry_name=data.get("ancestry", expected_ancestry).lower(),
            heritage=data.get("heritage", ""),
            background=data.get("background", ""),
            character_level=data.get("level", expected_level),
            ability_scores=data.get("ability_scores", {}),
            skills=data.get("skills", {}),
            equipment=data.get("equipment", []),
            raw_text="",
        )

        feats = []
        levels_data = data.get("levels", {})
        for level_str, slots in levels_data.items():
            try:
                level_num = int(level_str)
            except (ValueError, TypeError):
                continue
            if not isinstance(slots, dict):
                continue
            for slot_key, feat_name in slots.items():
                if not feat_name or not isinstance(feat_name, str):
                    continue
                slot_type = slot_key.replace("_feat", "")
                feats.append(ParsedFeatChoice(
                    name=feat_name,
                    slot_type=slot_type,
                    character_level=level_num,
                ))
        build.feats = feats

        return self._run_rules(build)
