# Future: Hybrid Retrieval with Qdrant + bge-m3

## Status: Planned (not implemented)

This document captures research on upgrading from ChromaDB (dense-only) to Qdrant
with full hybrid retrieval (dense + sparse + ColBERT) using bge-m3.

## Why

bge-m3 produces three types of embeddings:
- **Dense** (1024-dim) — standard semantic similarity
- **Sparse** (learned lexical weights) — precise keyword matching, better than BM25
- **ColBERT** (multi-vector, per-token) — late interaction scoring for nuanced matching

ChromaDB only supports dense vectors. Our benchmarks show bge-m3 underperforms
mxbai-embed-large on dense-only retrieval (bge-m3 scores ~0.55-0.63 vs mxbai ~0.76-0.81),
likely because its strength lies in the hybrid combination.

## Architecture

```
Current:
  Query → Ollama (dense only) → ChromaDB → ranked results

Proposed:
  Query → FlagEmbedding (dense + sparse + ColBERT) → Qdrant → fused results
             BGEM3FlagModel.encode()                   3 named vectors
                                                        score fusion
```

## Key Constraint: Ollama Can't Do It

Ollama's `/api/embed` returns dense vectors only. There is no sparse or ColBERT
output (GitHub issue ollama/ollama#6230, open since Aug 2024).

To get all three embedding types, use FlagEmbedding directly:

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
output = model.encode(
    sentences,
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=True,
)
# output["dense_vecs"]     → np.ndarray (N, 1024)
# output["lexical_weights"] → list[dict[token_id, weight]]
# output["colbert_vecs"]   → list[np.ndarray] (N, seq_len, 1024)
```

## Vector DB Comparison

| Database | Sparse | ColBERT | Embedded (no server) | Verdict |
|----------|--------|---------|---------------------|---------|
| **Qdrant** | Yes | Yes (multivector + MaxSim) | Yes (<20k pts) | Best fit |
| LanceDB | No (BM25 only) | Yes | Yes | No learned sparse |
| Milvus Lite | No (Lite mode) | No | Yes | Sparse needs full Milvus |
| Weaviate | No | No | Semi (subprocess) | No sparse/ColBERT |
| Vespa | Yes | Yes | No (Docker/JVM) | Too heavy |

## Qdrant Implementation Sketch

### Dependencies
```
pip install qdrant-client FlagEmbedding
```

FlagEmbedding pulls PyTorch + ~2GB model weights. Significant disk/memory cost.

### Collection Setup
```python
from qdrant_client import QdrantClient, models

client = QdrantClient(path="/home/shared_llm/vector_db/pf2e_qdrant")

client.create_collection(
    collection_name="foundry_bgem3_hybrid",
    vectors_config={
        "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(
            modifier=models.Modifier.IDF,  # IDF weighting for sparse
        ),
    },
    # ColBERT multivectors
    # Qdrant supports this via named multivector configs
)
```

### Hybrid Query
```python
from qdrant_client import models

results = client.query_points(
    collection_name="foundry_bgem3_hybrid",
    prefetch=[
        models.Prefetch(query=dense_vec, using="dense", limit=20),
        models.Prefetch(query=sparse_vec, using="sparse", limit=20),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),  # Reciprocal Rank Fusion
    limit=10,
)
```

### Expected Performance
- Dense-only (current): bge-m3 scores 0.55-0.63
- Hybrid (dense+sparse): expected 0.70-0.80 range
- Full hybrid (dense+sparse+ColBERT): expected 0.80+ (competitive with mxbai dense)

### Caveats
- Qdrant local mode is brute-force search — fine for our 16k docs, slow past ~50k
- For larger datasets, run `qdrant` as a Docker container (single container, easy)
- FlagEmbedding loads the full model in memory (~2-3GB VRAM or RAM)
- ColBERT vectors are large (seq_len * 1024 floats per document) — significant storage

## Decision

Deferred. mxbai-embed-large with ChromaDB (dense-only) achieves strong results
(0.76-0.81 relevance) on our PF2e data. The hybrid approach adds significant
complexity and dependencies for uncertain gains. Revisit when:
- Query quality issues emerge that dense search can't solve
- Ollama adds native sparse/ColBERT output (watch issue #6230)
- The dataset grows beyond ChromaDB's comfortable range
