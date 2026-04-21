"""Data structures for build query decomposition."""

from dataclasses import dataclass, field


@dataclass
class FeatSlot:
    """A single feat slot in a character build."""
    slot_type: str  # "class", "ancestry", "general", "skill"
    level: int      # Character level at which this slot is gained
    source: str     # Class name for class slots, ancestry name for ancestry slots


@dataclass
class FeatOption:
    """A single valid feat for a slot."""
    name: str
    level: int
    traits: list[str] = field(default_factory=list)
    prerequisites: str = ""
    rarity: str = "common"
    category: str = ""
    action_type: str = ""


@dataclass
class SlotOptions:
    """All valid options for a single feat slot."""
    slot: FeatSlot
    options: list[FeatOption] = field(default_factory=list)


@dataclass
class BuildSpec:
    """Parsed character build specification."""
    character_level: int
    class_name: str
    ancestry_name: str = ""
    dedications: list[str] = field(default_factory=list)


@dataclass
class BuildOptions:
    """Complete set of options for all slots in a build."""
    spec: BuildSpec
    slot_options: list[SlotOptions] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Build options for level {self.spec.character_level} {self.spec.ancestry_name} {self.spec.class_name}"]
        if self.spec.dedications:
            lines[0] += f" (dedications: {', '.join(self.spec.dedications)})"
        for so in self.slot_options:
            lines.append(f"\n  {so.slot.slot_type.upper()} feat slot (level {so.slot.level}): {len(so.options)} options")
            for opt in so.options[:5]:
                prereq = f" [prereq: {opt.prerequisites}]" if opt.prerequisites else ""
                lines.append(f"    - {opt.name} (lvl {opt.level}, {opt.rarity}){prereq}")
            if len(so.options) > 5:
                lines.append(f"    ... and {len(so.options) - 5} more")
        return "\n".join(lines)
