# Feat: RAG-Augmented Generation for Local Models

**Status:** Planned
**Priority:** High — highest ROI for reducing hallucinations
**Depends on:** Ollama GPU setup (done), ChromaDB ingestion (done), mxbai-embed-large (done)

## Problem

Local models (qwen3:32b, llama3.3:70b) hallucinate heavily on PF2e rules — inventing
feats, confusing class mechanics, fabricating action costs. Web search augmentation
helps slightly but DuckDuckGo results are too generic for niche TTRPG rules.

Meanwhile, we have 27,648 PF2e documents in ChromaDB with high-quality embeddings
(mxbai-embed-large, 0.76-0.81 relevance scores). This data is used for *post-hoc*
verification (auto_scorer) but never for *pre-generation* grounding.

## Solution

Inject relevant ChromaDB results into the prompt before calling local models,
similar to the existing `_search_and_augment()` pattern but hitting the local
vector DB instead of DuckDuckGo.

## Implementation Plan

### Step 1: RAG retrieval function

Add `_rag_augment()` to `providers.py` (or a new `rag.py` module):

```python
def _rag_augment(prompt: str, n_results: int = 10) -> str:
    """Query ChromaDB and prepend relevant PF2e rules as context."""
    # Reuse PF2eDB from auto_scorer (already has search interface)
    # Query mxbai collection for best results
    # Format results as structured context
    # Sort ascending by relevance (best chunk last — recency bias)
```

- Use `mxbai` collection (best benchmarked model)
- Retrieve 10 results, threshold at 0.70 relevance
- Sort ascending so most relevant chunk is closest to the question

### Step 2: Strict system prompt

Replace the current PF2e system prompt for local models with a grounding-focused one:

```
You are a Pathfinder 2e rules assistant. Answer ONLY using the provided context.
If the answer is not in the context, say "I don't have that rule available."
Never invent feat names, action costs, or mechanics.
```

This directly addresses the hallucination problem. Cloud models with broader training
can keep the current more permissive prompt.

### Step 3: Context assembly

Format the retrieved chunks with metadata:

```
## PF2e Rules Reference (use ONLY these as source):

### Exploit Vulnerability [feat, level 1]
Traits: Esoteric, Manipulate, Thaumaturge
[chunk text]

### Implement's Empowerment [feat, level 1]
Traits: Thaumaturge
[chunk text]

---

[user's actual question]
```

Key decisions:
- Include metadata (level, traits, prerequisites) — helps model reason about validity
- Sort by ascending relevance (best last) — models attend better to end of context
- Keep within ~4K tokens of context to leave room for generation in 8K window

### Step 4: Wire into call chain

In `_call_openai_compatible()`, before the existing search/Ollama block:

```python
if config.key.startswith("ollama-") and rag_enabled:
    prompt = _rag_augment(prompt)
    system_prompt = PF2E_STRICT_SYSTEM_PROMPT
```

Need to decide how to signal RAG enablement:
- Option A: New `--rag` CLI flag (explicit)
- Option B: Pack provides a `get_rag_config()` method (pack-driven)
- Option C: Auto-detect if ChromaDB is available (implicit)

**Recommendation:** Option B — keeps framework domain-agnostic. Pack returns
a RAG config (db path, collection, n_results, system prompt override) or None.

### Step 5: CLI integration

```bash
python cli.py run pf2e --providers ollama-llama3.3 --rag
# or automatically if pack defines RAG config:
python cli.py run pf2e --providers ollama-llama3.3
```

## Architecture Considerations

- PF2eDB import path: `packs/pf2e/auto_scorer.py` already does this — extract
  the DB access into a shared utility or let the pack provide a retrieval function
- ChromaDB path: read from env `PF2E_DB_PATH` (same as MCP server)
- Embedding model call: requires Ollama to embed the query — adds ~0.5s latency
- Don't RAG-augment the judge — it should evaluate the response independently

## Future Enhancements (separate feats)

- Re-ranker (cross-encoder) after retrieval — see `reranker.md`
- HyDE query transformation — see `hyde-query-transform.md`
- Hybrid search (BM25 + vector) — see `hybrid-retrieval-qdrant.md` (existing)

## Verification

1. Run same thaumaturge query with and without RAG, compare hallucination rate
2. Auto_scorer verification scores should improve significantly
3. Judge "Rule Legality" scores should increase
