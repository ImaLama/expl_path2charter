"""Text cleaning utilities for PF2e data sources."""

import re
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper using stdlib."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_foundry_html(html: str) -> str:
    """Strip HTML tags and FoundryVTT @UUID references from description text.

    Handles:
    - Standard HTML tags (<p>, <em>, <strong>, etc.)
    - @UUID[Compendium.pf2e.xxx.Item.Name]{Display Text} → Display Text
    - @UUID[Compendium.pf2e.xxx.Item.Name] → Name (de-slugified)
    - @Compendium references (older format)
    """
    if not html:
        return ""

    # Replace @UUID[...]{Display Text} with Display Text
    text = re.sub(r'@UUID\[[^\]]+\]\{([^}]+)\}', r'\1', html)
    # Replace @UUID[Compendium.pf2e.xxx.Item.SlugName] with the last segment
    text = re.sub(
        r'@UUID\[Compendium\.pf2e\.[^]]*\.Item\.([^\]]+)\]',
        lambda m: m.group(1).replace('-', ' ').title(),
        text
    )
    # Catch any remaining @UUID refs
    text = re.sub(r'@UUID\[[^\]]+\]', '', text)
    # Old-style @Compendium refs
    text = re.sub(r'@Compendium\[[^\]]+\]\{([^}]+)\}', r'\1', text)
    text = re.sub(r'@Compendium\[[^\]]+\]', '', text)

    # Strip HTML tags
    stripper = _HTMLStripper()
    stripper.feed(text)
    result = stripper.get_text()

    # Collapse whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def strip_pf2etools_tags(text: str) -> str:
    """Strip Pf2eTools {@tag content|extra} markup, keeping display text.

    Handles: {@spell Fireball}, {@feat Shield Block|CRB}, {@damage 2d6},
    {@dice 1d20+5}, {@dc 15}, {@action Strike}, {@item Longsword|CRB}, etc.
    """
    if not text:
        return ""

    # {@tag content|source|extra} → content
    # {@tag content} → content
    result = re.sub(r'\{@\w+\s+([^|}]+)[^}]*\}', r'\1', text)
    return result.strip()


def flatten_pf2etools_entries(entries: list) -> str:
    """Recursively flatten Pf2eTools entries array into plain text.

    Entries can be strings or dicts with nested structures like:
    {"type": "list", "items": [...]}, {"type": "table", ...},
    {"type": "pf2-h3", "name": "...", "entries": [...]}, etc.
    """
    parts = []
    for entry in entries:
        if isinstance(entry, str):
            parts.append(strip_pf2etools_tags(entry))
        elif isinstance(entry, dict):
            # Handle named sections
            if "name" in entry:
                parts.append(entry["name"] + ":")
            # Recurse into entries
            if "entries" in entry:
                parts.append(flatten_pf2etools_entries(entry["entries"]))
            # Handle lists
            if "items" in entry:
                items = entry["items"]
                for item in items:
                    if isinstance(item, str):
                        parts.append("- " + strip_pf2etools_tags(item))
                    elif isinstance(item, dict):
                        if "entries" in item:
                            parts.append(flatten_pf2etools_entries(item["entries"]))
                        elif "entry" in item:
                            parts.append(strip_pf2etools_tags(str(item["entry"])))
            # Handle table rows
            if "rows" in entry:
                for row in entry["rows"]:
                    if isinstance(row, list):
                        parts.append(" | ".join(str(cell) for cell in row))
    return " ".join(parts)
