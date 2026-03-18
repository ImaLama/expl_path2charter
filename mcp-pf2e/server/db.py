"""ChromaDB client wrapper for the MCP server."""

import json
from pathlib import Path

import chromadb

# Add parent dir to path so we can import from ingest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest.embeddings import OllamaEmbeddingFunction

DEFAULT_DB_PATH = "/home/shared_llm/vector_db/pf2e_chroma"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class PF2eDB:
    """ChromaDB wrapper for PF2e rules search."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        ollama_url: str = DEFAULT_OLLAMA_URL,
    ):
        self.client = chromadb.PersistentClient(path=db_path)
        self.ollama_url = ollama_url
        # Cache embedding functions per model
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
            # Legacy unsuffixed collections use nomic
            model = "nomic-embed-text"
        if model not in self._embed_fns:
            self._embed_fns[model] = OllamaEmbeddingFunction(
                model=model, base_url=self.ollama_url
            )
        return self._embed_fns[model]

    def _get_collection(self, source: str):
        return self.client.get_collection(
            name=source,
            embedding_function=self._embed_fn_for(source),
        )

    def search(
        self,
        query: str,
        source: str = "foundry",
        content_type: str | None = None,
        level_min: int | None = None,
        level_max: int | None = None,
        traits: list[str] | None = None,
        n_results: int = 5,
    ) -> list[dict]:
        """Semantic search with metadata filters."""
        collection = self._get_collection(source)

        # Build where clause
        where_clauses = []
        if content_type:
            where_clauses.append({"content_type": content_type})
        if level_min is not None:
            where_clauses.append({"level": {"$gte": level_min}})
        if level_max is not None:
            where_clauses.append({"level": {"$lte": level_max}})
        # Note: traits are stored comma-separated. $contains doesn't work
        # on strings in this ChromaDB version, so we post-filter traits.

        where = None
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        # Over-fetch if we need to post-filter by traits
        fetch_n = min(n_results, 20)
        if traits:
            fetch_n = min(n_results * 5, 100)

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

                # Post-filter by traits if requested
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
                    "relevance_score": round(1 - results["distances"][0][i], 4),
                    "text": results["documents"][0][i],
                })
                if len(items) >= n_results:
                    break
        return items

    def get_entry(
        self,
        name: str,
        source: str = "foundry",
        content_type: str | None = None,
    ) -> dict | None:
        """Exact name lookup returning full raw JSON."""
        collection = self._get_collection(source)

        where = {"name": name}
        if content_type:
            where = {"$and": [{"name": name}, {"content_type": content_type}]}

        results = collection.get(
            where=where,
            include=["metadatas"],
            limit=1,
        )

        if results["ids"]:
            meta = results["metadatas"][0]
            raw = meta.get("raw_json", "{}")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"name": name, "error": "raw_json not parseable"}
        return None

    def list_content_types(self, source: str = "foundry") -> list[str]:
        """List distinct content types in a collection."""
        collection = self._get_collection(source)
        # ChromaDB doesn't have a distinct() operation, so we sample
        results = collection.get(include=["metadatas"], limit=10000)
        types = set()
        for meta in results["metadatas"]:
            if meta.get("content_type"):
                types.add(meta["content_type"])
        return sorted(types)

    def list_collections(self) -> list[dict]:
        """List all available collections with counts."""
        return [
            {"name": c.name, "count": c.count()}
            for c in self.client.list_collections()
        ]
