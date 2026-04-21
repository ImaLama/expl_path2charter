"""
PF2e RAG-augmented AutoScorer.

Extracts feat/spell/feature names from model responses and verifies them
against the local ChromaDB vector database of official PF2e content.
"""

import re
import sys
from pathlib import Path

from llm_eval.types import AutoScorer, Prompt, GenerationResult

# Add mcp-pf2e to path for ChromaDB access
_MCP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "mcp-pf2e"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


# Labels that precede game entity names in character builds
_FEAT_LABELS = [
    r"ancestry feat",
    r"class feat",
    r"general feat",
    r"skill feat",
    r"archetype feat",
    r"bonus feat",
    r"feat",
    r"heritage",
    r"background",
]

_SPELL_LABELS = [
    r"cantrip",
    r"spell",
    r"focus spell",
    r"innate spell",
]

_FEATURE_LABELS = [
    r"class feature",
    r"ancestry feature",
    r"feature",
    r"dedication",
    r"innovation",
    r"implement",
]

ALL_LABELS = _FEAT_LABELS + _SPELL_LABELS + _FEATURE_LABELS


def extract_entity_names(text: str) -> list[str]:
    """Extract PF2e game entity names from a character build response.

    Looks for patterns like:
    - "**Feat:** Shield Block"
    - "Ancestry Feat: Goblin Scuttle"
    - "- Shield Block (level 1 general feat)"
    - "Level 1: Shield Block"
    - "| Shield Block | General | 1 |"
    - Bullet points under feat/spell headers
    """
    names = set()

    # Pattern 1: "Label: Name" or "**Label:** Name" or "**Label**: **Name**"
    label_pattern = "|".join(ALL_LABELS)
    p1 = re.compile(
        rf"\*{{0,2}}(?:{label_pattern})s?\*{{0,2}}\s*[:—]\s*\*{{0,2}}([A-Z][A-Za-z\'\-\s]+)",
        re.IGNORECASE,
    )
    for m in p1.finditer(text):
        name = _clean_name(m.group(1))
        if name:
            names.add(name)

    # Pattern 2: "**Level X**: **Name**." or "**Level X**: Name (Type)"
    # This is the most common format in character builds
    p2 = re.compile(
        r"\*{0,2}Level\s+\d+\*{0,2}\s*[:—]\s*\*{0,2}([A-Z][A-Za-z\'\-\s]+?)\*{0,2}\s*[.,(]",
        re.IGNORECASE,
    )
    for m in p2.finditer(text):
        name = _clean_name(m.group(1))
        if name:
            names.add(name)

    # Pattern 3: "- **Name** (description)" or "* **Name**." bullet points
    p3 = re.compile(
        r"[-•*]\s+\*{2}([A-Z][A-Za-z\'\-\s]{2,}?)\*{2}[\s.,;:(]",
    )
    for m in p3.finditer(text):
        name = _clean_name(m.group(1))
        if name:
            names.add(name)

    # Pattern 4: "- Name (level X type feat)" without bold
    p4 = re.compile(
        r"[-•*]\s+([A-Z][A-Za-z\'\-\s]{2,}?)\s*\(",
    )
    for m in p4.finditer(text):
        name = _clean_name(m.group(1))
        if name:
            names.add(name)

    # Pattern 5: Table rows "| Name | ... |"
    p5 = re.compile(r"\|\s*([A-Z][A-Za-z\'\-\s]{2,}?)\s*\|")
    for m in p5.finditer(text):
        name = _clean_name(m.group(1))
        if name and len(name.split()) <= 5:
            names.add(name)

    # Pattern 6: "Basic Devotion -> **Name**" archetype patterns
    p6 = re.compile(
        r"(?:Basic|Advanced)\s+\w+\s*[-:>→]+\s*\*{0,2}([A-Z][A-Za-z\'\-\s]+?)\*{0,2}[.,;]",
        re.IGNORECASE,
    )
    for m in p6.finditer(text):
        name = _clean_name(m.group(1))
        if name:
            names.add(name)

    return sorted(names)


def _clean_name(raw: str) -> str | None:
    """Clean and validate an extracted name."""
    name = raw.strip().rstrip(".,;:!?")
    # Remove trailing markdown
    name = name.rstrip("*").strip()
    # Remove level indicators
    name = re.sub(r"\s*\(.*$", "", name)
    # Skip overly short or generic strings
    if len(name) < 3 or name.lower() in (
        "the", "and", "for", "with", "level", "feat", "spell",
        "none", "note", "see", "class", "general", "skill",
        "ancestry", "heritage", "background", "equipment",
        "str", "dex", "con", "int", "wis", "cha",
        # Common section headers and labels that aren't game entities
        "deity", "cause", "key ability", "expert", "master", "trained",
        "legendary", "untrained", "ancestry feats", "class feats",
        "general feats", "skill feats", "archetype feats", "feats",
        "spells", "cantrips", "equipment loadout", "ability scores",
        "starting stats", "combat stats", "skill training",
        "background feat", "personality", "backstory",
        "requirements", "special", "trigger", "effect",
        "rules note", "thrown trident strike",
        "exploit vulnerability weakness damage",
        "adventurer's pack",
    ):
        return None
    # Skip if it's all lowercase (likely not a proper name)
    if name[0].islower():
        return None
    return name


class PF2eAutoScorer(AutoScorer):
    """Verifies PF2e game entities against the local ChromaDB database."""

    def __init__(
        self,
        db_path: str = str(Path(__file__).resolve().parent.parent.parent.parent / "_state" / "vector_db" / "pf2e_chroma"),
        collection: str = "foundry_mxbai",
    ):
        self.db_path = db_path
        self.collection = collection
        self._db = None

    def _get_db(self):
        if self._db is None:
            from server.db import PF2eDB
            self._db = PF2eDB(db_path=self.db_path)
        return self._db

    def score(self, prompt: Prompt, result: GenerationResult) -> dict:
        """Extract entity names and verify against the database."""
        db = self._get_db()

        # Extract names from the model's response
        claimed_names = extract_entity_names(result.content)

        if not claimed_names:
            return {
                "verification": {
                    "score": 3,
                    "details": "No entity names could be extracted from response",
                },
                "fabrication_check": {
                    "score": 3,
                    "details": "No entity names could be extracted from response",
                },
            }

        verified = []
        not_found = []

        for name in claimed_names:
            # Try exact name match
            entry = db.get_entry(name, source=self.collection)
            if entry and "error" not in entry:
                level = entry.get("system", {}).get("level", {}).get("value", "?")
                etype = entry.get("type", "?")
                verified.append(f"{name} ({etype}, level {level})")
            else:
                # Fallback: semantic search with high threshold
                results = db.search(
                    query=name,
                    source=self.collection,
                    n_results=1,
                )
                if results and results[0]["relevance_score"] > 0.85:
                    match = results[0]
                    verified.append(
                        f"{name} → {match['name']} "
                        f"({match['content_type']}, level {match['level']})"
                    )
                else:
                    not_found.append(name)

        # Calculate scores
        total = len(claimed_names)
        verified_count = len(verified)
        fabricated_count = len(not_found)

        verified_ratio = verified_count / max(total, 1)
        verification_score = max(1, min(5, 1 + int(verified_ratio * 4)))

        if fabricated_count == 0:
            fabrication_score = 5
        elif fabricated_count <= 2:
            fabrication_score = 3
        elif fabricated_count <= 5:
            fabrication_score = 2
        else:
            fabrication_score = 1

        return {
            "verification": {
                "score": verification_score,
                "details": (
                    f"{verified_count}/{total} verified. "
                    f"Found: {', '.join(verified[:10])}"
                    + (f" (+{verified_count - 10} more)" if verified_count > 10 else "")
                ),
            },
            "fabrication_check": {
                "score": fabrication_score,
                "details": (
                    f"{fabricated_count} not found"
                    + (f": {', '.join(not_found[:10])}" if not_found else "")
                ),
            },
        }

    def get_verification_context(self, result: GenerationResult) -> str | None:
        """Generate verification context to inject into the judge prompt.

        This is called separately from score() so the pack can pass it
        to the judge prompt builder.
        """
        db = self._get_db()
        claimed_names = extract_entity_names(result.content)

        if not claimed_names:
            return None

        verified = []
        not_found = []

        for name in claimed_names:
            entry = db.get_entry(name, source=self.collection)
            if entry and "error" not in entry:
                level = entry.get("system", {}).get("level", {}).get("value", "?")
                etype = entry.get("type", "?")
                verified.append(f"- {name} ({etype}, level {level})")
            else:
                results = db.search(query=name, source=self.collection, n_results=1)
                if results and results[0]["relevance_score"] > 0.85:
                    match = results[0]
                    verified.append(
                        f"- {name} → matched as \"{match['name']}\" "
                        f"({match['content_type']}, level {match['level']})"
                    )
                else:
                    not_found.append(f"- \"{name}\" (not found)")

        lines = ["## Automated verification against official PF2e database:"]

        if verified:
            lines.append("\nVerified as EXISTING in official PF2e content:")
            lines.extend(verified)

        if not_found:
            lines.append("\nNOT FOUND in the database (potentially fabricated or misspelled):")
            lines.extend(not_found)

        lines.append(
            "\nUse this verification data when scoring Rule Legality. "
            "Items not found may be fabricated, misspelled, or from content "
            "not yet in the database."
        )

        return "\n".join(lines)
