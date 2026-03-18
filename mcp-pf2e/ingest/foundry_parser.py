"""Parse FoundryVTT PF2e JSON files into normalized documents."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .text_cleaners import strip_foundry_html


@dataclass
class PF2eDocument:
    """Normalized document for ChromaDB ingestion."""
    id: str
    name: str
    content_type: str
    level: int
    traits: list[str] = field(default_factory=list)
    prerequisites: str = ""
    source_book: str = ""
    rarity: str = "common"
    text: str = ""
    raw_json: str = ""


# Map directory names to content types
PACK_TYPE_MAP = {
    "feats": "feat",
    "classes": "class",
    "class-features": "class-feature",
    "ancestries": "ancestry",
    "ancestry-features": "ancestry-feature",
    "heritages": "heritage",
    "backgrounds": "background",
    "spells": "spell",
    "equipment": "equipment",
    "actions": "action",
    "conditions": "condition",
    "deities": "deity",
    "domains": "domain",
    "hazards": "hazard",
}


def _extract_prerequisites(sys: dict) -> str:
    prereqs = sys.get("prerequisites", {}).get("value", [])
    parts = []
    for p in prereqs:
        if isinstance(p, dict):
            parts.append(p.get("value", str(p)))
        elif isinstance(p, str):
            parts.append(p)
    return "; ".join(parts)


def parse_foundry_file(filepath: Path, pack_name: str) -> PF2eDocument | None:
    """Parse a single FoundryVTT JSON file into a PF2eDocument."""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"  SKIP {filepath.name}: {e}")
        return None

    if not isinstance(data, dict) or "name" not in data:
        return None

    sys = data.get("system", {})
    content_type = PACK_TYPE_MAP.get(pack_name, data.get("type", pack_name))

    name = data.get("name", "")
    level_raw = sys.get("level", {})
    if isinstance(level_raw, dict):
        level = level_raw.get("value", 0) or 0
    else:
        level = level_raw or 0
    level = int(level)

    traits = sys.get("traits", {}).get("value", []) or []
    rarity = sys.get("traits", {}).get("rarity", "common") or "common"
    prerequisites = _extract_prerequisites(sys)
    source_book = sys.get("publication", {}).get("title", "") or ""
    description = strip_foundry_html(sys.get("description", {}).get("value", ""))

    # Build embedding text
    rules_keys = ", ".join(r.get("key", "") for r in sys.get("rules", []) if r.get("key"))
    text_parts = [
        f"{name} ({content_type}, level {level})",
        f"Traits: {', '.join(traits)}" if traits else "",
        f"Prerequisites: {prerequisites}" if prerequisites else "",
        f"Rarity: {rarity}" if rarity != "common" else "",
        description,
        f"Rules: {rules_keys}" if rules_keys else "",
    ]
    text = ". ".join(p for p in text_parts if p)

    # Limit raw_json size for metadata (ChromaDB has practical limits)
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) > 8000:
        raw = json.dumps({"_filepath": str(filepath), "name": name}, ensure_ascii=False)

    doc_id = data.get("_id", filepath.stem)

    return PF2eDocument(
        id=f"foundry_{doc_id}",
        name=name,
        content_type=content_type,
        level=level,
        traits=traits,
        prerequisites=prerequisites,
        source_book=source_book,
        rarity=rarity,
        text=text,
        raw_json=raw,
    )


def parse_foundry_packs(
    packs_dir: Path,
    categories: list[str] | None = None,
) -> list[PF2eDocument]:
    """Parse all FoundryVTT pack directories into documents.

    Args:
        packs_dir: Path to packs/pf2e/ directory
        categories: Optional list of pack names to process (e.g., ["feats", "spells"])
    """
    documents = []
    target_packs = categories or list(PACK_TYPE_MAP.keys())

    for pack_name in target_packs:
        pack_path = packs_dir / pack_name
        if not pack_path.exists():
            print(f"  Pack not found: {pack_name}")
            continue

        json_files = [f for f in pack_path.rglob("*.json") if f.name != "_folders.json"]
        print(f"  {pack_name}: {len(json_files)} files")

        for filepath in json_files:
            doc = parse_foundry_file(filepath, pack_name)
            if doc:
                documents.append(doc)

    return documents
