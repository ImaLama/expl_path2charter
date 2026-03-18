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
        # Truncate based on model context limits:
        #   nomic-embed-text: 8192 tokens (~6000 chars)
        #   bge-m3: 8192 tokens (~6000 chars)
        #   mxbai-embed-large: 512 tokens (~1500 chars)
        max_chars = 1500 if "mxbai" in self.model else 6000
        cleaned = [(t[:max_chars] if t.strip() else "(empty)") for t in input]

        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": cleaned},
            timeout=120.0,
        )
        if response.status_code != 200:
            # Retry one-by-one to isolate bad inputs
            print(f"\n  Embed error {response.status_code} on batch of {len(cleaned)}, retrying one-by-one...")
            embeddings = []
            for j, text in enumerate(cleaned):
                single = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": [text]},
                    timeout=120.0,
                )
                if single.status_code == 200:
                    embeddings.append(single.json()["embeddings"][0])
                else:
                    # Replace with zero vector on failure
                    print(f"    Skip doc {j}: {text[:60]}...")
                    dim = len(embeddings[0]) if embeddings else 1024
                    embeddings.append([0.0] * dim)
            return embeddings
        return response.json()["embeddings"]
