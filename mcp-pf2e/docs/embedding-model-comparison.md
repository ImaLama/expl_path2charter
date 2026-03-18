# Embedding Model Comparison

## Models Tested

| Model | Dimensions | Context | Size | Collection Suffix |
|-------|-----------|---------|------|-------------------|
| nomic-embed-text | 768 | 8192 tokens | 274 MB | `_nomic` (or unsuffixed) |
| mxbai-embed-large | 1024 | 512 tokens | 669 MB | `_mxbai` |
| bge-m3 | 1024 | 8192 tokens | 1.2 GB | `_bgem3` |

Note: bge-m3 is tested in dense-only mode (ChromaDB limitation).
Its sparse + ColBERT capabilities are unused. See `hybrid-retrieval-qdrant.md`.

## Benchmark Results

All queries run against the `foundry` data source (16,177 documents).
Scores are cosine similarity (higher = better match).

### Query 1: "Twin Feint prerequisites" (short exact)

| Model | #1 Result | Score | Correct? |
|-------|-----------|-------|----------|
| nomic | Natural Ambition | 0.67 | No |
| **mxbai** | **Twin Feint** | **0.81** | **Yes** |
| bgem3 | Twin Distraction | 0.63 | Partial (#2 is correct) |

### Query 2: "what feats work with a two-weapon fighter focused on debuffing" (long contextual)

| Model | #1 Result | Score | Quality |
|-------|-----------|-------|---------|
| nomic | Double Slice | 0.77 | Good (relevant) |
| **mxbai** | **Dual-Weapon Blitz** | **0.78** | **Best (most specific)** |
| bgem3 | Twin Feint | 0.60 | OK |

### Query 3: "fighter weapon mastery class feature level 13" (class feature)

| Model | #1 Result | Score | Quality |
|-------|-----------|-------|---------|
| **nomic** | **Weapon Legend** | **0.84** | **Good (L13 match)** |
| mxbai | Fighter Weapon Mastery | 0.83 | Good (exact name, wrong level) |
| bgem3 | Martial Weapon Mastery | 0.68 | OK |

### Query 4: "feats that trigger on a failed saving throw" (rules interaction)

| Model | #1 Result | Score | Quality |
|-------|-----------|-------|---------|
| nomic | Invoke Celestial Privilege | 0.78 | Relevant |
| **mxbai** | **Shake It Off** | **0.78** | **Relevant** |
| bgem3 | Find Fault | 0.61 | Somewhat relevant |

### Query 5: "good setup for action economy builds" (vague/implied)

| Model | #1 Result | Score | Quality |
|-------|-----------|-------|---------|
| nomic | Clockwork Celerity | 0.58 | Somewhat relevant |
| **mxbai** | **Quick Setup** | **0.65** | **Somewhat relevant** |
| bgem3 | Fortify Camp | 0.52 | Off-target |

## Summary

```
                  Exact   Contextual  Class    Rules    Vague    Overall
  nomic           ✗       ✓           ✓✓       ✓        ~        Good for broad
  mxbai           ✓✓      ✓✓          ✓        ✓        ~        Best overall
  bgem3 (dense)   ~       ~           ✓        ~        ✗        Weakest (missing hybrid)
```

**Winner: mxbai-embed-large** — consistently strongest across query types despite
its shorter context window (512 tokens). Its 1024-dim embeddings are more
discriminative for structured game rules text.

**nomic-embed-text** is a solid second — better on broad/class-feature queries
where longer context helps.

**bge-m3** (dense-only) underperforms — likely because its architecture is
optimized for hybrid retrieval (dense + sparse + ColBERT), which ChromaDB
doesn't support. See `hybrid-retrieval-qdrant.md` for future plans.

## Ingestion Times

All timings on local hardware with Ollama serving the model:

| Model | Foundry (16,177 docs) | Pf2eTools (11,471 docs) | Total |
|-------|----------------------|------------------------|-------|
| nomic-embed-text | ~80s | ~60s | ~2.5 min |
| mxbai-embed-large | ~160s | ~130s | ~5 min |
| bge-m3 | ~240s | ~135s | ~6 min |
