"""Data structures for build validation."""

from dataclasses import dataclass, field


@dataclass
class ParsedFeatChoice:
    """A single feat chosen in the build."""
    name: str
    slot_type: str = ""         # "class", "ancestry", "general", "skill", "archetype", ""
    character_level: int = 0    # Level at which this feat was taken (0 = unknown)


@dataclass
class ParsedBuild:
    """Structured representation of an LLM-generated build."""
    class_name: str = ""
    ancestry_name: str = ""
    heritage: str = ""
    background: str = ""
    character_level: int = 0
    ability_scores: dict[str, int] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)  # skill_name → rank (trained/expert/master/legendary)
    feats: list[ParsedFeatChoice] = field(default_factory=list)
    spells: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ValidationError:
    """A single validation error."""
    rule: str           # e.g., "feat_existence", "level_legality"
    severity: str       # "error", "warning"
    message: str
    feat_name: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Complete validation output."""
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    verified_feats: list[str] = field(default_factory=list)
    build: ParsedBuild = field(default_factory=ParsedBuild)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        lines = []
        if self.is_valid:
            lines.append(f"VALID — {len(self.verified_feats)} feats verified, {len(self.warnings)} warnings")
        else:
            lines.append(f"INVALID — {len(self.errors)} errors, {len(self.warnings)} warnings")
        for e in self.errors:
            lines.append(f"  ERROR [{e.rule}]: {e.message}")
        for w in self.warnings:
            lines.append(f"  WARN  [{w.rule}]: {w.message}")
        return "\n".join(lines)
