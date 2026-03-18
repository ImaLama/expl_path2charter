"""ChromaDB collection loader with batch upsert."""

import chromadb
from chromadb.api.types import EmbeddingFunction

from .foundry_parser import PF2eDocument


def load_documents(
    client: chromadb.ClientAPI,
    collection_name: str,
    documents: list[PF2eDocument],
    embedding_fn: EmbeddingFunction,
    batch_size: int = 200,
    wipe: bool = False,
) -> int:
    """Load documents into a ChromaDB collection.

    Returns the number of documents ingested.
    """
    if wipe:
        try:
            client.delete_collection(collection_name)
            print(f"  Wiped collection: {collection_name}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    ingested = 0
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]

        ids = [d.id for d in batch]
        texts = [d.text for d in batch]
        metadatas = [
            {
                "name": d.name,
                "content_type": d.content_type,
                "level": d.level,
                "traits": ",".join(d.traits),
                "prerequisites": d.prerequisites,
                "source_book": d.source_book,
                "rarity": d.rarity,
                "raw_json": d.raw_json,
            }
            for d in batch
        ]

        collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
        ingested += len(batch)
        print(f"  Progress: {ingested}/{len(documents)} ingested", end="\r")

    print(f"  Done: {ingested} documents in collection '{collection_name}' (total: {collection.count()})")
    return ingested
