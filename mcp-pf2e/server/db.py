"""ChromaDB client wrapper for the MCP server."""

import json
from pathlib import Path

import chromadb

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest.embeddings import OllamaEmbeddingFunction
from ingest.foundry_parser import CONTENT_TYPE_TO_COLLECTION, BUILD_RELEVANT_COLLECTIONS

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = str(_PROJECT_ROOT / "_state" / "vector_db" / "pf2e_chroma")
DEFAULT_OLLAMA_URL = "http://localhost:11434"

_MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class PF2eDB:
    """ChromaDB wrapper for PF2e rules search."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = "mxbai",
    ):
        self.client = chromadb.PersistentClient(path=db_path)
        self.ollama_url = ollama_url
        self.model = model
        self._embed_fns: dict[str, OllamaEmbeddingFunction] = {}

    def _embed_fn_for(self, collection_name: str) -> OllamaEmbeddingFunction:
        """Return the correct embedding function based on collection suffix."""
        if collection_name.endswith("_mxbai"):
            model = "mxbai-embed-large"
        elif collection_name.endswith("_bgem3"):
            model = "bge-m3"
        elif collection_name.endswith("_nomic"):
            model = "nomic-embed-text"
        else:
            model = "nomic-embed-text"
        if model not in self._embed_fns:
            self._embed_fns[model] = OllamaEmbeddingFunction(
                model=model, base_url=self.ollama_url
            )
        return self._embed_fns[model]

    def _get_collection(self, name: str):
        return self.client.get_collection(
            name=name,
            embedding_function=self._embed_fn_for(name),
        )

    def _resolve_collections(self, content_type: str | None = None, source: str | None = None) -> list[str]:
        """Map content_type to collection name(s).

        If source is provided (legacy), use it as a literal collection name.
        If content_type is provided, map to the specific per-type collection.
        If neither, fan out across all build-relevant collections.
        """
        if source:
            return [source]
        if content_type:
            base = CONTENT_TYPE_TO_COLLECTION.get(content_type, content_type + "s")
            return [f"{base}_{self.model}"]
        return [f"{base}_{self.model}" for base in BUILD_RELEVANT_COLLECTIONS]

    def _embed_query(self, query: str, collection_name: str) -> list[float] | None:
        """Embed a query with model-specific prefix. Returns None for non-mxbai (use query_texts)."""
        embed_fn = self._embed_fn_for(collection_name)
        if embed_fn.model == "mxbai-embed-large":
            return embed_fn([_MXBAI_QUERY_PREFIX + query])[0]
        return None

    def _query_single_collection(
        self,
        collection_name: str,
        query: str,
        where: dict | None,
        fetch_n: int,
        traits: list[str] | None,
    ) -> list[dict]:
        """Query a single collection and return scored items."""
        try:
            collection = self._get_collection(collection_name)
        except Exception:
            return []

        query_embedding = self._embed_query(query, collection_name)
        if query_embedding is not None:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        else:
            results = collection.query(
                query_texts=[query],
                n_results=fetch_n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

        items = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                entry_traits = meta.get("traits", "").split(",") if meta.get("traits") else []

                if traits:
                    if not all(t in entry_traits for t in traits):
                        continue

                items.append({
                    "name": meta.get("name", ""),
                    "content_type": meta.get("content_type", ""),
                    "level": meta.get("level", 0),
                    "traits": entry_traits,
                    "prerequisites": meta.get("prerequisites", ""),
                    "source_book": meta.get("source_book", ""),
                    "rarity": meta.get("rarity", "common"),
                    "category": meta.get("category", ""),
                    "action_type": meta.get("action_type", ""),
                    "relevance_score": round(1 - results["distances"][0][i], 4),
                    "text": results["documents"][0][i],
                })
        return items

    def search(
        self,
        query: str,
        source: str | None = None,
        content_type: str | None = None,
        level_min: int | None = None,
        level_max: int | None = None,
        traits: list[str] | None = None,
        category: str | None = None,
        action_type: str | None = None,
        n_results: int = 5,
    ) -> list[dict]:
        """Semantic search with metadata filters across per-type collections."""
        collections = self._resolve_collections(content_type, source)

        # Build where clause
        where_clauses = []
        if content_type and not source:
            where_clauses.append({"content_type": content_type})
        if level_min is not None:
            where_clauses.append({"level": {"$gte": level_min}})
        if level_max is not None:
            where_clauses.append({"level": {"$lte": level_max}})
        if category:
            where_clauses.append({"category": category})
        if action_type:
            where_clauses.append({"action_type": action_type})

        where = None
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        fetch_n = min(n_results, 20)
        if traits:
            fetch_n = min(n_results * 5, 100)

        # Fan-out query across collections, merge by relevance
        all_items = []
        for coll_name in collections:
            items = self._query_single_collection(coll_name, query, where, fetch_n, traits)
            all_items.extend(items)

        all_items.sort(key=lambda x: x["relevance_score"], reverse=True)
        return all_items[:n_results]

    def get_entry(
        self,
        name: str,
        source: str | None = None,
        content_type: str | None = None,
    ) -> dict | None:
        """Exact name lookup returning full raw JSON.

        Searches the appropriate per-type collection, or iterates all if
        content_type is not specified. For chunked entries, returns the raw
        JSON from chunk 0.
        """
        collections = self._resolve_collections(content_type, source)

        for coll_name in collections:
            try:
                collection = self._get_collection(coll_name)
            except Exception:
                continue

            where = {"name": name}
            if content_type:
                where = {"$and": [{"name": name}, {"content_type": content_type}]}

            results = collection.get(
                where=where,
                include=["metadatas"],
                limit=5,
            )

            if not results["ids"]:
                continue

            for meta in results["metadatas"]:
                raw = meta.get("raw_json", "")
                if raw:
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        continue

        return None

    def list_content_types(self, source: str | None = None) -> list[str]:
        """List distinct content types across all collections."""
        types = set()
        if source:
            collections = [source]
        else:
            collections = [c.name for c in self.client.list_collections()]

        for coll_name in collections:
            try:
                collection = self._get_collection(coll_name)
                results = collection.get(include=["metadatas"], limit=1000)
                for meta in results["metadatas"]:
                    if meta.get("content_type"):
                        types.add(meta["content_type"])
            except Exception:
                continue
        return sorted(types)

    def list_collections(self) -> list[dict]:
        """List all available collections with counts."""
        return [
            {"name": c.name, "count": c.count()}
            for c in self.client.list_collections()
        ]
