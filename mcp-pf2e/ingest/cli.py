"""CLI for ingesting PF2e data into ChromaDB."""

import argparse
import sys
import time
from pathlib import Path

import chromadb

from .embeddings import OllamaEmbeddingFunction
from .foundry_parser import parse_foundry_packs, PACK_TYPE_MAP
from .pf2etools_parser import parse_pf2etools_data
from .loader import load_documents

DEFAULT_DATA_DIR = "/home/shared_llm/static_data/pf2"
DEFAULT_DB_PATH = "/home/shared_llm/vector_db/pf2e_chroma"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Existing collections "foundry" and "pf2etools" were created with nomic-embed-text
# before the model suffix convention was added. Future runs should use the
# --embed-model flag which appends _nomic or _mxbai to collection names.
# The old unsuffixed collections are left intact for backward compatibility.
EMBED_MODEL_SUFFIX = {
    "nomic-embed-text": "nomic",
    "mxbai-embed-large": "mxbai",
    "bge-m3": "bgem3",
}


def main():
    parser = argparse.ArgumentParser(description="Ingest PF2e JSON data into ChromaDB")
    parser.add_argument(
        "--source",
        choices=["foundry", "pf2etools", "all"],
        default="all",
        help="Which data source to ingest",
    )
    parser.add_argument(
        "--embed-model",
        default="nomic-embed-text",
        help="Ollama embedding model name (default: nomic-embed-text)",
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Root data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"ChromaDB storage path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama base URL (default: {DEFAULT_OLLAMA_URL})",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        help="Only ingest specific categories (e.g., feats spells classes)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for ChromaDB upsert (default: 200)",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete existing collections before ingesting",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    db_path = Path(args.db_path)
    db_path.mkdir(parents=True, exist_ok=True)

    # Determine collection name suffix from embed model
    suffix = EMBED_MODEL_SUFFIX.get(args.embed_model, args.embed_model.split("-")[0])

    # Initialize ChromaDB and embedding function
    client = chromadb.PersistentClient(path=str(db_path))
    embed_fn = OllamaEmbeddingFunction(model=args.embed_model, base_url=args.ollama_url)

    # Test embedding connection
    print(f"Testing Ollama embedding ({args.embed_model})...")
    try:
        result = embed_fn(["test"])
        print(f"  OK - embedding dimension: {len(result[0])}")
    except Exception as e:
        print(f"  FAILED: {e}")
        print(f"  Make sure Ollama is running and model is pulled:")
        print(f"    ollama pull {args.embed_model}")
        sys.exit(1)

    start = time.time()

    # Ingest FoundryVTT
    if args.source in ("foundry", "all"):
        foundry_dir = data_dir / "pf2e" / "packs" / "pf2e"
        collection_name = f"foundry_{suffix}"
        if foundry_dir.exists():
            print(f"\n=== FoundryVTT → {collection_name} ===")
            docs = parse_foundry_packs(foundry_dir, categories=args.categories)
            print(f"  Parsed {len(docs)} documents")
            if docs:
                load_documents(client, collection_name, docs, embed_fn, args.batch_size, args.wipe)
        else:
            print(f"FoundryVTT data not found at {foundry_dir}")

    # Ingest Pf2eTools
    if args.source in ("pf2etools", "all"):
        tools_dir = data_dir / "Pf2eTools" / "data"
        collection_name = f"pf2etools_{suffix}"
        if tools_dir.exists():
            print(f"\n=== Pf2eTools → {collection_name} ===")
            docs = parse_pf2etools_data(tools_dir, categories=args.categories)
            print(f"  Parsed {len(docs)} documents")
            if docs:
                load_documents(client, collection_name, docs, embed_fn, args.batch_size, args.wipe)
        else:
            print(f"Pf2eTools data not found at {tools_dir}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.1f}s")

    # Summary
    print("\nCollections:")
    for c in client.list_collections():
        print(f"  {c.name}: {c.count()} documents")


if __name__ == "__main__":
    main()
