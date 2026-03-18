"""Ollama embedding function for ChromaDB."""

import httpx
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings


class OllamaEmbeddingFunction(EmbeddingFunction):
    """ChromaDB-compatible embedding function using Ollama's /api/embed endpoint."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.base_url = base_url

    def __call__(self, input: Documents) -> Embeddings:
        # Ensure no empty strings (Ollama rejects them)
        # Truncate to ~6000 chars (~2000 tokens) to stay within nomic-embed-text context
        cleaned = [(t[:6000] if t.strip() else "(empty)") for t in input]

        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": cleaned},
            timeout=120.0,
        )
        if response.status_code != 200:
            # Log the failing batch for debugging
            lens = [len(t) for t in cleaned]
            print(f"\n  Embed error {response.status_code}: batch size={len(cleaned)}, text lengths={min(lens)}-{max(lens)}")
            print(f"  Response: {response.text[:200]}")
            response.raise_for_status()
        return response.json()["embeddings"]
