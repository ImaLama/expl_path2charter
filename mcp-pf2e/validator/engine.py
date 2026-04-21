"""Build validation engine — orchestrates all validation rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .types import ParsedBuild, ValidationResult
from .parser import parse_build
from .rules import (
    check_feat_existence,
    check_level_legality,
    check_slot_counts,
    check_class_feat_access,
    check_prerequisites,
    check_archetype_rules,
)

try:
    from server.db import PF2eDB
except ImportError:
    PF2eDB = None


class BuildValidator:
    """Orchestrates all validation rules for a PF2e character build."""

    def __init__(self, db: "PF2eDB | None" = None):
        self._db = db

    def validate(
        self,
        text: str,
        expected_class: str = "",
        expected_ancestry: str = "",
        expected_level: int = 0,
    ) -> ValidationResult:
        """Full validation pipeline.

        1. Parse the build text into structured form
        2. Run all validation rules
        3. Collect errors and warnings
        4. Return structured result
        """
        build = parse_build(
            text,
            expected_class=expected_class,
            expected_ancestry=expected_ancestry,
            expected_level=expected_level,
        )

        all_errors = []

        # Run rules in priority order
        all_errors.extend(check_feat_existence(build, self._db))
        all_errors.extend(check_level_legality(build, self._db))
        all_errors.extend(check_slot_counts(build))
        all_errors.extend(check_class_feat_access(build, self._db))
        all_errors.extend(check_prerequisites(build, self._db))
        all_errors.extend(check_archetype_rules(build, self._db))

        errors = [e for e in all_errors if e.severity == "error"]
        warnings = [e for e in all_errors if e.severity == "warning"]

        # Build verified feats list (feats that passed existence check)
        errored_feats = {e.feat_name for e in errors if e.feat_name}
        verified = [f.name for f in build.feats if f.name not in errored_feats]

        return ValidationResult(
            errors=errors,
            warnings=warnings,
            verified_feats=verified,
            build=build,
        )
