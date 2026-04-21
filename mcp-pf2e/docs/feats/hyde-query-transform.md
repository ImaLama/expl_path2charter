# Feat: HyDE Query Transformation

**Status:** Planned
**Priority:** Low — nice-to-have after RAG + re-ranker are working
**Depends on:** RAG-augmented generation (feat)

## Problem

User queries are often vague or conversational:
- "how does my thaumaturge deal more damage"
- "what feats synergize with melee spellcasting"

These queries embed poorly because they don't contain the specific terminology
that appears in the rule chunks ("Exploit Vulnerability", "Implement's Empowerment",
"Esoteric Antithesis").

## Solution

HyDE (Hypothetical Document Embeddings): before searching, ask the LLM to generate
a hypothetical answer, then embed *that* as the search query. The hypothetical answer
contains relevant terminology that matches the actual rule chunks much better.

## Implementation Plan

1. Take user query
2. Call a fast local model (qwen3:32b or even a smaller model) with:
   ```
   Answer this PF2e question in 2-3 sentences. Include specific feat names,
   action names, and game terms. Do not worry about accuracy — this is for
   search purposes only.

   Question: [user query]
   ```
3. Embed the hypothetical answer instead of the raw query
4. Proceed with normal retrieval + re-ranking

### Considerations

- Adds one LLM call (~2-5s) before retrieval — acceptable for eval, not for interactive
- The hypothetical answer will contain hallucinated feat names — that's fine,
  they're close enough in embedding space to retrieve the real ones
- Could cache HyDE results for repeated queries
- Only use for vague queries — exact feat name lookups should skip this

## Verification

- Compare retrieval recall on 10 vague queries with/without HyDE
- Measure if retrieved chunks are more topically relevant
