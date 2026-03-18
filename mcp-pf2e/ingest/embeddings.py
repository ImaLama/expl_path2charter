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
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": input},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["embeddings"]
