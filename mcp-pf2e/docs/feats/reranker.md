# Feat: Cross-Encoder Re-Ranker

**Status:** Planned
**Priority:** Medium — significant quality boost after RAG augmentation is in place
**Depends on:** RAG-augmented generation (feat)

## Problem

Vector search returns top-K chunks by embedding similarity, but embedding models
can return semantically adjacent but irrelevant results. For example, searching
"thaumaturge melee feats" might return Thaumaturge class description, Thaumaturge
lore entries, or Fighter melee feats — all semantically close but not what we need.

Irrelevant chunks in the context window waste tokens and can mislead the model.

## Solution

After retrieving top-K results from ChromaDB, run a cross-encoder re-ranker to
re-score each (query, chunk) pair. Cross-encoders see both texts together and
produce much more accurate relevance scores than bi-encoder embeddings.

## Implementation Plan

### Model

`cross-encoder/ms-marco-MiniLM-L-6-v2` — 22M params, fast, well-benchmarked.
Runs on CPU in ~10ms per pair, so 20 candidates = ~200ms. Negligible overhead.

### Steps

1. `pip install sentence-transformers` (includes cross-encoder support)
2. Add `_rerank()` function:
   ```python
   from sentence_transformers import CrossEncoder

   _reranker = None

   def _rerank(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
       global _reranker
       if _reranker is None:
           _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

       pairs = [(query, c["text"]) for c in chunks]
       scores = _reranker.predict(pairs)
       ranked = sorted(zip(scores, chunks), reverse=True)
       return [c for _, c in ranked[:top_k]]
   ```
3. Call between ChromaDB retrieval and context assembly:
   - Retrieve 20 candidates from ChromaDB
   - Re-rank to top 5-7
   - Assemble context from re-ranked results

### Considerations

- Model downloads ~80MB on first use — cache it
- CPU-only is fine for this model size
- Lazy-load to avoid import overhead when re-ranker isn't needed
- Could also be useful for the auto_scorer's verification lookups

## Verification

- Compare retrieval precision with/without re-ranker on a set of test queries
- Measure latency impact (should be <500ms for 20 candidates)
