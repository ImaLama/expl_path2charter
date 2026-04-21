"""Parse FoundryVTT PF2e JSON files into normalized documents."""

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from .text_cleaners import strip_foundry_html

TOKEN_THRESHOLD = 400

CONTENT_TYPE_TO_COLLECTION = {
    "feat": "feats",
    "spell": "spells",
    "class": "classes",
    "class-feature": "class_features",
    "ancestry": "ancestries",
    "ancestry-feature": "ancestries",
    "heritage": "ancestries",
    "background": "backgrounds",
    "equipment": "equipment",
    "action": "actions",
    "condition": "conditions",
    "deity": "deities",
    "domain": "deities",
    "hazard": "hazards",
    "archetype": "feats",
    "creature": "creatures",
    "companion": "companions",
    "vehicle": "vehicles",
    "organization": "misc",
    "place": "misc",
    "event": "misc",
    "language": "misc",
    "skill": "misc",
    "table": "misc",
    "trait": "misc",
    "group": "misc",
    "ability": "misc",
}

BUILD_RELEVANT_COLLECTIONS = [
    "feats", "spells", "classes", "class_features",
    "ancestries", "backgrounds", "equipment", "actions",
]


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
    category: str = ""
    has_prerequisites: bool = False
    action_type: str = ""
    parent_id: str = ""
    chunk_index: int = 0
    is_chunk: bool = False


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


def parse_foundry_file(filepath: Path, pack_name: str) -> tuple[PF2eDocument, str] | None:
    """Parse a single FoundryVTT JSON file into a PF2eDocument and raw HTML."""
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
    raw_html = sys.get("description", {}).get("value", "") or ""
    description = strip_foundry_html(raw_html)

    # Extract richer metadata
    category = sys.get("category", "") or ""
    action_type_raw = sys.get("actionType", {})
    action_type = action_type_raw.get("value", "") if isinstance(action_type_raw, dict) else ""
    has_prerequisites = bool(prerequisites)

    # Build embedding text with structured header prefix
    rules_keys = ", ".join(r.get("key", "") for r in sys.get("rules", []) if r.get("key"))
    header_parts = [f"[{content_type.upper()}] {name}"]
    if level:
        header_parts.append(f"Level {level}")
    if category:
        header_parts.append(f"Category: {category}")
    if traits:
        header_parts.append(f"Traits: {', '.join(traits)}")
    if prerequisites:
        header_parts.append(f"Prerequisites: {prerequisites}")
    if rarity != "common":
        header_parts.append(f"Rarity: {rarity}")
    header = " | ".join(header_parts)
    body_parts = [description]
    if rules_keys:
        body_parts.append(f"Rules: {rules_keys}")
    body = " ".join(p for p in body_parts if p)
    text = f"{header}\n{body}" if body else header

    # Limit raw_json size for metadata (ChromaDB has practical limits)
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) > 8000:
        raw = json.dumps({"_filepath": str(filepath), "name": name}, ensure_ascii=False)

    doc_id = data.get("_id", filepath.stem)

    doc = PF2eDocument(
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
        category=category,
        has_prerequisites=has_prerequisites,
        action_type=action_type or "",
    )
    return doc, raw_html


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _split_html_sections(html: str) -> list[str]:
    """Split HTML on <hr> tags, falling back to <h3> if sections are still long."""
    sections = re.split(r'<hr\s*/?>', html)
    result = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if _estimate_tokens(strip_foundry_html(section)) > TOKEN_THRESHOLD:
            subsections = re.split(r'<h3[^>]*>', section)
            result.extend(s.strip() for s in subsections if s.strip())
        else:
            result.append(section)
    return result if len(result) > 1 else [html]


def split_long_entry(doc: PF2eDocument, raw_html: str) -> list[PF2eDocument]:
    """Split a document that exceeds the token threshold into sub-chunks."""
    if _estimate_tokens(doc.text) <= TOKEN_THRESHOLD:
        return [doc]

    sections = _split_html_sections(raw_html)
    if len(sections) <= 1:
        return [doc]

    # Build header that prefixes every chunk
    header_parts = [f"[{doc.content_type.upper()}] {doc.name}"]
    if doc.level:
        header_parts.append(f"Level {doc.level}")
    if doc.category:
        header_parts.append(f"Category: {doc.category}")
    if doc.traits:
        header_parts.append(f"Traits: {', '.join(doc.traits)}")
    header = " | ".join(header_parts)

    chunks = []
    for i, section_html in enumerate(sections):
        section_text = strip_foundry_html(section_html)
        if not section_text.strip():
            continue
        chunk_text = f"{header}\n{section_text}"
        chunk = replace(
            doc,
            id=f"{doc.id}__chunk_{i}",
            text=chunk_text,
            raw_json=doc.raw_json if i == 0 else "",
            parent_id=doc.id,
            chunk_index=i,
            is_chunk=True,
        )
        chunks.append(chunk)

    return chunks if chunks else [doc]


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
            result = parse_foundry_file(filepath, pack_name)
            if result:
                doc, raw_html = result
                documents.extend(split_long_entry(doc, raw_html))

    return documents
