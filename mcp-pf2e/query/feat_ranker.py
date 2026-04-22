"""Rank feat options by semantic relevance to a build concept via ChromaDB embeddings."""

import numpy as np
import chromadb

from query.types import BuildOptions
from query.static_reader import get_feat_data
from ingest.embeddings import OllamaEmbeddingFunction
from ingest.text_cleaners import strip_foundry_html
from server.db import DEFAULT_DB_PATH

_MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_FEATS_COLLECTION = "feats_mxbai"
_DESC_MAX_CHARS = 200


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _get_feat_description(feat_name: str) -> str | None:
    """Get a cleaned, truncated description for a feat."""
    entry = get_feat_data(feat_name)
    if not entry:
        return None
    raw_desc = entry.get("system", {}).get("description", {}).get("value", "")
    if not raw_desc:
        return None
    cleaned = strip_foundry_html(raw_desc).strip()
    if len(cleaned) > _DESC_MAX_CHARS:
        cleaned = cleaned[:_DESC_MAX_CHARS] + "..."
    return cleaned if cleaned else None


def _find_prereq_feat_names(feat_name: str, valid_names: set[str]) -> set[str]:
    """Find valid feat names that appear in a feat's prerequisites."""
    entry = get_feat_data(feat_name)
    if not entry:
        return set()
    prereqs_raw = entry.get("system", {}).get("prerequisites", {}).get("value", [])
    found = set()
    for p in prereqs_raw:
        pval = p.get("value", "") if isinstance(p, dict) else str(p)
        pval_lower = pval.lower()
        for candidate in valid_names:
            if candidate.lower() in pval_lower:
                found.add(candidate)
    return found


def rank_feats_for_concept(
    concept: str,
    options: BuildOptions,
    db_path: str = DEFAULT_DB_PATH,
    top_class: int = 10,
    top_other: int = 5,
) -> dict[str, list[dict]]:
    """Rank each slot's feats by relevance to the build concept.

    Embeds the concept once, fetches pre-stored feat embeddings from ChromaDB,
    computes cosine similarity. Returns dict keyed by "{level}_{slot_type}".

    Prerequisite chain members of top-ranked feats are always included
    with descriptions even if they didn't rank individually.
    """
    # Embed the concept
    embed_fn = OllamaEmbeddingFunction(model="mxbai-embed-large")
    concept_emb = np.array(
        embed_fn([_MXBAI_QUERY_PREFIX + concept])[0]
    )

    # Open ChromaDB collection
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection(_FEATS_COLLECTION)

    # Group slots by type for batched queries
    slots_by_type: dict[str, list] = {}
    for so in options.slot_options:
        slots_by_type.setdefault(so.slot.slot_type, []).append(so)

    ranked_slots = {}

    for slot_type, slot_list in slots_by_type.items():
        # Collect all unique feat names across all levels for this type
        all_names = set()
        for so in slot_list:
            all_names.update(o.name for o in so.options)

        if not all_names:
            continue

        top_n = top_class if slot_type == "class" else top_other

        # Batch-fetch pre-stored embeddings from ChromaDB
        name_list = sorted(all_names)
        result = collection.get(
            where={"name": {"$in": name_list}},
            include=["metadatas", "embeddings"],
        )

        # Deduplicate by name, keep first embedding
        name_to_emb: dict[str, np.ndarray] = {}
        for i, meta in enumerate(result["metadatas"]):
            name = meta.get("name", "")
            if name and name not in name_to_emb:
                name_to_emb[name] = np.array(result["embeddings"][i])

        # Compute cosine similarity for all feats
        scores: dict[str, float] = {}
        for name, emb in name_to_emb.items():
            scores[name] = _cosine_similarity(concept_emb, emb)

        # Find prerequisite chain members for top-ranked feats
        top_ranked_names = sorted(scores, key=lambda n: scores[n], reverse=True)[:top_n * 2]
        prereq_names = set()
        for feat_name in top_ranked_names:
            prereq_names.update(_find_prereq_feat_names(feat_name, all_names))

        # Build per-slot rankings
        for so in slot_list:
            slot_names = {o.name for o in so.options}
            slot_key = f"{so.slot.level}_{so.slot.slot_type}"

            ranked = []
            for name in sorted(slot_names):
                score = scores.get(name, 0.0)
                ranked.append({"name": name, "score": score})

            ranked.sort(key=lambda x: x["score"], reverse=True)

            # Mark top-N + prereq chain members for description display
            for i, entry in enumerate(ranked):
                show = i < top_n or entry["name"] in prereq_names
                if show:
                    entry["description"] = _get_feat_description(entry["name"])
                entry["show_description"] = show

            ranked_slots[slot_key] = ranked

    return ranked_slots
