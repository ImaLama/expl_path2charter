"""
Pack discovery — scans packs/*/pack.py for ChallengePack implementations.

Directories starting with '_' (like _template) are skipped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .types import ChallengePack

PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"


def discover_packs() -> list[ChallengePack]:
    """Scan packs/*/pack.py and return all discovered ChallengePack instances."""
    packs = []
    if not PACKS_DIR.is_dir():
        return packs

    for pack_dir in sorted(PACKS_DIR.iterdir()):
        if not pack_dir.is_dir() or pack_dir.name.startswith("_"):
            continue
        pack_file = pack_dir / "pack.py"
        if not pack_file.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"packs.{pack_dir.name}.pack", pack_file
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            get_pack = getattr(module, "get_pack", None)
            if callable(get_pack):
                pack = get_pack()
                if isinstance(pack, ChallengePack):
                    packs.append(pack)
        except Exception as e:
            print(f"Warning: failed to load pack '{pack_dir.name}': {e}")

    return packs


def get_pack_by_name(name: str) -> ChallengePack | None:
    """Find a pack by name. Returns None if not found."""
    for pack in discover_packs():
        if pack.name == name:
            return pack
    return None
