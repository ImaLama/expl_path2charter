"""Read PF2e class/ancestry/feat data directly from FoundryVTT JSON files."""

import json
import re
from functools import lru_cache
from pathlib import Path

from .types import FeatOption

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATIC_ROOT = _PROJECT_ROOT / "_state" / "static_data" / "pf2" / "pf2e" / "packs" / "pf2e"


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace("'", "").replace("'", "")


def _parse_feat_file(filepath: Path) -> FeatOption | None:
    """Parse a single FoundryVTT feat JSON into a FeatOption."""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or "name" not in data:
        return None

    sys = data.get("system", {})
    level_raw = sys.get("level", {})
    level = level_raw.get("value", 0) if isinstance(level_raw, dict) else (level_raw or 0)
    level = int(level)

    traits_obj = sys.get("traits", {})
    traits = traits_obj.get("value", []) if isinstance(traits_obj, dict) else []
    rarity = traits_obj.get("rarity", "common") if isinstance(traits_obj, dict) else "common"

    prereqs = sys.get("prerequisites", {}).get("value", [])
    prereq_parts = []
    for p in prereqs:
        if isinstance(p, dict):
            prereq_parts.append(p.get("value", str(p)))
        elif isinstance(p, str):
            prereq_parts.append(p)
    prerequisites = "; ".join(prereq_parts)

    category = sys.get("category", "") or ""
    action_type_raw = sys.get("actionType", {})
    action_type = action_type_raw.get("value", "") if isinstance(action_type_raw, dict) else ""

    return FeatOption(
        name=data["name"],
        level=level,
        traits=traits or [],
        prerequisites=prerequisites,
        rarity=rarity or "common",
        category=category,
        action_type=action_type or "",
    )


def _extract_level_from_dir(dirname: str) -> int | None:
    """Extract level number from directory name like 'level-4'."""
    m = re.match(r"level-(\d+)", dirname)
    return int(m.group(1)) if m else None


def _list_feats_from_level_dirs(base_dir: Path, max_level: int) -> list[FeatOption]:
    """List feats from a directory organized as level-N/ subdirectories."""
    feats = []
    if not base_dir.exists():
        return feats
    for level_dir in base_dir.iterdir():
        if not level_dir.is_dir():
            continue
        lvl = _extract_level_from_dir(level_dir.name)
        if lvl is None or lvl > max_level:
            continue
        for filepath in level_dir.glob("*.json"):
            feat = _parse_feat_file(filepath)
            if feat:
                feats.append(feat)
    return feats


def _list_feats_flat(base_dir: Path, max_level: int) -> list[FeatOption]:
    """List feats from a flat directory (no level subdirs), filtering by JSON level field."""
    feats = []
    if not base_dir.exists():
        return feats
    for filepath in base_dir.glob("*.json"):
        feat = _parse_feat_file(filepath)
        if feat and feat.level <= max_level:
            feats.append(feat)
    return feats


@lru_cache(maxsize=32)
def get_class_data(class_name: str) -> dict | None:
    """Load a class JSON file and return its full data."""
    filepath = _STATIC_ROOT / "classes" / f"{_slugify(class_name)}.json"
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


@lru_cache(maxsize=32)
def get_feat_slot_levels(class_name: str) -> dict[str, list[int]]:
    """Get feat slot level arrays for a class.

    Returns dict with keys: class, ancestry, general, skill
    Each value is a sorted list of character levels where that slot is gained.
    """
    data = get_class_data(class_name)
    if not data:
        return {"class": [], "ancestry": [], "general": [], "skill": []}
    sys = data.get("system", {})
    return {
        "class": sorted(sys.get("classFeatLevels", {}).get("value", [])),
        "ancestry": sorted(sys.get("ancestryFeatLevels", {}).get("value", [])),
        "general": sorted(sys.get("generalFeatLevels", {}).get("value", [])),
        "skill": sorted(sys.get("skillFeatLevels", {}).get("value", [])),
    }


def list_class_feats(class_name: str, max_level: int) -> list[FeatOption]:
    """List all class feats for a given class up to max_level."""
    base_dir = _STATIC_ROOT / "feats" / "class" / _slugify(class_name)
    return _list_feats_from_level_dirs(base_dir, max_level)


def list_ancestry_feats(ancestry_name: str, max_level: int) -> list[FeatOption]:
    """List all ancestry feats for a given ancestry up to max_level."""
    base_dir = _STATIC_ROOT / "feats" / "ancestry" / _slugify(ancestry_name)
    return _list_feats_from_level_dirs(base_dir, max_level)


def list_general_feats(max_level: int) -> list[FeatOption]:
    """List all general feats up to max_level."""
    base_dir = _STATIC_ROOT / "feats" / "general"
    return _list_feats_from_level_dirs(base_dir, max_level)


def list_skill_feats(max_level: int) -> list[FeatOption]:
    """List all skill feats up to max_level."""
    base_dir = _STATIC_ROOT / "feats" / "skill"
    return _list_feats_from_level_dirs(base_dir, max_level)


def list_archetype_feats(archetype_name: str, max_level: int) -> list[FeatOption]:
    """List all archetype feats up to max_level.

    Archetype feats are in a flat directory (no level subdirs),
    so we filter by the JSON level field.
    """
    base_dir = _STATIC_ROOT / "feats" / "archetype" / _slugify(archetype_name)
    return _list_feats_flat(base_dir, max_level)


def list_available_classes() -> list[str]:
    """List all available class names."""
    classes_dir = _STATIC_ROOT / "classes"
    if not classes_dir.exists():
        return []
    return sorted(f.stem for f in classes_dir.glob("*.json"))


def list_available_ancestries() -> list[str]:
    """List all available ancestry names from the feats directory."""
    ancestry_dir = _STATIC_ROOT / "feats" / "ancestry"
    if not ancestry_dir.exists():
        return []
    return sorted(d.name for d in ancestry_dir.iterdir() if d.is_dir())


@lru_cache(maxsize=32)
def get_class_trained_skills(class_name: str) -> dict:
    """Get class skill training info.

    Returns dict with:
      'fixed': list of always-trained skills
      'additional': number of extra skill choices
      'custom': any custom lore skill
    """
    data = get_class_data(class_name)
    if not data:
        return {"fixed": [], "additional": 0, "custom": ""}
    ts = data.get("system", {}).get("trainedSkills", {})
    return {
        "fixed": ts.get("value", []),
        "additional": ts.get("additional", 0),
        "custom": ts.get("custom", ""),
    }


_ALL_SKILLS = [
    "acrobatics", "arcana", "athletics", "crafting", "deception",
    "diplomacy", "intimidation", "medicine", "nature", "occultism",
    "performance", "religion", "society", "stealth", "survival", "thievery",
]


def list_skill_feats_for_skills(
    trained_skills: list[str],
    max_level: int,
) -> list[FeatOption]:
    """List skill feats whose prerequisites are met by the given trained skills.

    A skill feat is eligible if:
    - It has no prerequisites, OR
    - Its 'trained in X' prereq matches one of the trained skills
    """
    all_feats = list_skill_feats(max_level)
    trained_lower = {s.lower() for s in trained_skills}

    eligible = []
    for feat in all_feats:
        if not feat.prerequisites:
            eligible.append(feat)
            continue

        prereq_lower = feat.prerequisites.lower()
        if "trained in" not in prereq_lower:
            eligible.append(feat)
            continue

        # Check if any trained skill matches the prerequisite
        matched = False
        for skill in trained_lower:
            if skill in prereq_lower:
                matched = True
                break

        # Handle "Arcana, Nature, Occultism, or Religion" style prereqs
        if not matched and ("," in prereq_lower or " or " in prereq_lower):
            for skill in trained_lower:
                if skill in prereq_lower:
                    matched = True
                    break

        if matched:
            eligible.append(feat)

    return eligible


def group_skill_feats_by_skill(
    trained_skills: list[str],
    max_level: int,
) -> dict[str, list[FeatOption]]:
    """Group eligible skill feats by their prerequisite skill.

    Returns dict like {"Intimidation": [feat1, feat2], "Athletics": [feat3], "Any": [feat4]}.
    """
    eligible = list_skill_feats_for_skills(trained_skills, max_level)
    groups: dict[str, list[FeatOption]] = {}

    for feat in eligible:
        if not feat.prerequisites:
            groups.setdefault("Any", []).append(feat)
            continue

        prereq_lower = feat.prerequisites.lower()
        placed = False
        for skill in _ALL_SKILLS:
            if skill in prereq_lower:
                groups.setdefault(skill.title(), []).append(feat)
                placed = True
                break

        if not placed:
            groups.setdefault("Other", []).append(feat)

    return groups


def list_heritages(ancestry_name: str) -> list[str]:
    """List all heritage names for an ancestry."""
    heritage_dir = _STATIC_ROOT / "heritages" / _slugify(ancestry_name)
    if not heritage_dir.exists():
        return []
    names = []
    for f in heritage_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "name" in data:
                names.append(data["name"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return sorted(names)


def list_backgrounds() -> list[str]:
    """List all available background names."""
    bg_dir = _STATIC_ROOT / "backgrounds"
    if not bg_dir.exists():
        return []
    names = []
    for f in bg_dir.rglob("*.json"):
        if f.name == "_folders.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                names.append(data["name"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return sorted(names)


def _fuzzy_match(name: str, candidates: list[str]) -> str | None:
    """Find the best fuzzy match for a name in a list of candidates."""
    name_lower = name.lower().strip()
    for c in candidates:
        if c.lower() == name_lower:
            return c
    for c in candidates:
        if name_lower in c.lower() or c.lower() in name_lower:
            return c
    return None


@lru_cache(maxsize=32)
def get_ancestry_data(ancestry_name: str) -> dict | None:
    """Load ancestry JSON and return its full data."""
    filepath = _STATIC_ROOT / "ancestries" / f"{_slugify(ancestry_name)}.json"
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def get_background_data(background_name: str) -> dict | None:
    """Load a background JSON by name (fuzzy match against available backgrounds)."""
    bg_dir = _STATIC_ROOT / "backgrounds"
    if not bg_dir.exists():
        return None
    for f in bg_dir.rglob("*.json"):
        if f.name == "_folders.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("name", "").lower() == background_name.lower():
                return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


@lru_cache(maxsize=None)
def get_class_features(class_name: str, max_level: int = 20) -> list[str]:
    """Get auto-granted class feature names up to a given level."""
    data = get_class_data(class_name)
    if not data:
        return []
    items = data.get("system", {}).get("items", {})
    features = []
    for key, item in items.items():
        lvl = item.get("level", 99)
        if isinstance(lvl, int) and lvl <= max_level:
            name = item.get("name", "")
            if name:
                features.append(name)
    return features


def list_available_archetypes() -> list[str]:
    """List all available archetype names."""
    arch_dir = _STATIC_ROOT / "feats" / "archetype"
    if not arch_dir.exists():
        return []
    return sorted(d.name for d in arch_dir.iterdir() if d.is_dir())
