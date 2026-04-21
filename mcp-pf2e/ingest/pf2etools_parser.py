"""Parse Pf2eTools JSON files into normalized documents."""

import json
from pathlib import Path

from .foundry_parser import PF2eDocument, TOKEN_THRESHOLD, _estimate_tokens
from .text_cleaners import strip_pf2etools_tags, flatten_pf2etools_entries
from dataclasses import replace


# Map top-level JSON keys to content types
ENTRY_KEY_MAP = {
    "feat": "feat",
    "spell": "spell",
    "class": "class",
    "classFeature": "class-feature",
    "subclassFeature": "class-feature",
    "ancestry": "ancestry",
    "heritage": "heritage",
    "versatileHeritage": "heritage",
    "background": "background",
    "action": "action",
    "item": "equipment",
    "baseitem": "equipment",
    "archetype": "archetype",
    "condition": "condition",
    "deity": "deity",
    "domain": "domain",
    "creature": "creature",
    "hazard": "hazard",
    "ritual": "spell",
    "vehicle": "vehicle",
    "ability": "ability",
    "disease": "condition",
    "curse": "condition",
    "companion": "companion",
    "companionAbility": "companion",
    "familiar": "companion",
    "familiarAbility": "companion",
    "optionalFeature": "feat",
    "organization": "organization",
    "place": "place",
    "event": "event",
    "language": "language",
    "skill": "skill",
    "table": "table",
    "trait": "trait",
    "group": "group",
}

# Categories relevant for character building
BUILD_RELEVANT_KEYS = {
    "feat", "spell", "class", "classFeature", "subclassFeature",
    "ancestry", "heritage", "versatileHeritage", "background",
    "action", "item", "archetype",
}


def _split_pf2etools_entry(doc: PF2eDocument, entries: list) -> list[PF2eDocument]:
    """Split a long pf2etools doc by its top-level entries list."""
    if _estimate_tokens(doc.text) <= TOKEN_THRESHOLD or len(entries) <= 1:
        return [doc]

    header_parts = [f"[{doc.content_type.upper()}] {doc.name}"]
    if doc.level:
        header_parts.append(f"Level {doc.level}")
    if doc.traits:
        header_parts.append(f"Traits: {', '.join(doc.traits)}")
    header = " | ".join(header_parts)

    chunks = []
    current_parts = []
    current_tokens = _estimate_tokens(header)

    def flush(idx):
        if not current_parts:
            return
        section_text = " ".join(current_parts)
        chunk = replace(
            doc,
            id=f"{doc.id}__chunk_{idx}",
            text=f"{header}\n{section_text}",
            raw_json=doc.raw_json if idx == 0 else "",
            parent_id=doc.id,
            chunk_index=idx,
            is_chunk=True,
        )
        chunks.append(chunk)

    chunk_idx = 0
    for entry in entries:
        if isinstance(entry, str):
            part = strip_pf2etools_tags(entry)
        elif isinstance(entry, dict) and "name" in entry:
            part = entry["name"] + ": " + flatten_pf2etools_entries(entry.get("entries", []))
        else:
            part = flatten_pf2etools_entries([entry])
        part_tokens = _estimate_tokens(part)
        if current_tokens + part_tokens > TOKEN_THRESHOLD and current_parts:
            flush(chunk_idx)
            chunk_idx += 1
            current_parts = []
            current_tokens = _estimate_tokens(header)
        current_parts.append(part)
        current_tokens += part_tokens

    flush(chunk_idx)
    return chunks if chunks else [doc]


def _slugify(name: str, source: str) -> str:
    slug = name.lower().replace(" ", "-").replace("'", "")
    return f"tools_{source}_{slug}"


def _parse_entry(entry: dict, content_type: str, filepath: Path) -> PF2eDocument | None:
    """Parse a single Pf2eTools entry dict into a PF2eDocument."""
    name = entry.get("name", "")
    if not name:
        return None

    source = entry.get("source", "")
    level_raw = entry.get("level", 0) or 0
    if isinstance(level_raw, str):
        level_raw = level_raw.rstrip("+")
    try:
        level = int(level_raw)
    except (ValueError, TypeError):
        level = 0

    traits = entry.get("traits", []) or []
    if isinstance(traits, dict):
        traits = traits.get("value", []) or []

    prereqs_raw = entry.get("prerequisites", "")
    if isinstance(prereqs_raw, list):
        prereqs_raw = "; ".join(str(p) for p in prereqs_raw)
    elif isinstance(prereqs_raw, dict):
        prereqs_raw = str(prereqs_raw)
    prerequisites = strip_pf2etools_tags(str(prereqs_raw)) if prereqs_raw else ""

    rarity = "common"
    if isinstance(traits, list):
        for r in ("uncommon", "rare", "unique"):
            if r in traits:
                rarity = r
                traits = [t for t in traits if t != r]
                break

    # Build text from entries
    entries = entry.get("entries", [])
    description = flatten_pf2etools_entries(entries) if entries else ""

    # Additional text from special fields
    extra_parts = []
    if entry.get("trigger"):
        extra_parts.append(f"Trigger: {strip_pf2etools_tags(str(entry['trigger']))}")
    if entry.get("requirements"):
        extra_parts.append(f"Requirements: {strip_pf2etools_tags(str(entry['requirements']))}")
    if entry.get("frequency"):
        freq = entry["frequency"]
        if isinstance(freq, dict):
            extra_parts.append(f"Frequency: {freq.get('entry', str(freq))}")
        else:
            extra_parts.append(f"Frequency: {freq}")

    # Richer metadata
    category = entry.get("category", "") or ""
    action_type = ""
    activity = entry.get("activity", {})
    if isinstance(activity, dict) and activity.get("entry"):
        action_type = str(activity["entry"])
    has_prerequisites = bool(prerequisites)

    # Build embedding text with structured header prefix
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
    body_parts = [" ".join(extra_parts), description]
    body = " ".join(p for p in body_parts if p)
    text = f"{header}\n{body}" if body else header

    raw = json.dumps(entry, ensure_ascii=False)
    if len(raw) > 8000:
        raw = json.dumps({"_filepath": str(filepath), "name": name, "source": source}, ensure_ascii=False)

    return PF2eDocument(
        id=_slugify(name, source),
        name=name,
        content_type=content_type,
        level=level,
        traits=traits,
        prerequisites=prerequisites,
        source_book=source,
        rarity=rarity,
        text=text,
        raw_json=raw,
        category=category,
        has_prerequisites=has_prerequisites,
        action_type=action_type,
    )


def parse_pf2etools_data(
    data_dir: Path,
    categories: list[str] | None = None,
    build_relevant_only: bool = True,
) -> list[PF2eDocument]:
    """Parse Pf2eTools data directory into documents.

    Args:
        data_dir: Path to Pf2eTools/data/ directory
        categories: Optional list of entry keys to process
        build_relevant_only: If True, only process build-relevant content types
    """
    documents = []
    seen_ids = set()

    target_keys = set(categories) if categories else (
        BUILD_RELEVANT_KEYS if build_relevant_only else set(ENTRY_KEY_MAP.keys())
    )

    # Walk all JSON files in data directory
    json_files = sorted(data_dir.rglob("*.json"))
    print(f"  Scanning {len(json_files)} JSON files in Pf2eTools data/")

    for filepath in json_files:
        # Skip index files, fluff files, generated data
        if filepath.name.startswith("index") or filepath.name.startswith("fluff"):
            continue
        if "generated" in filepath.parts:
            continue

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        # Check each potential entry key in the file
        for entry_key, content_type in ENTRY_KEY_MAP.items():
            if entry_key not in data or entry_key not in target_keys:
                continue

            entries = data[entry_key]
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                doc = _parse_entry(entry, content_type, filepath)
                if doc and doc.id not in seen_ids:
                    seen_ids.add(doc.id)
                    raw_entries = entry.get("entries", [])
                    for chunk in _split_pf2etools_entry(doc, raw_entries):
                        documents.append(chunk)

    # Report counts by content type
    type_counts = {}
    for doc in documents:
        type_counts[doc.content_type] = type_counts.get(doc.content_type, 0) + 1
    for ct, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {ct}: {count}")

    return documents
