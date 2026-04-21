# Future Potential Improvements

Catalogued from design discussions (2026-04-21). Grouped by layer, roughly priority-ordered within each group.

## Build Quality (Generation Layer) — Highest Impact

These address the core problem: local models failing at rule-compliant build assembly.

### 1. Template/Exemplar Builds
Hand-author 10-20 canonical builds as structured JSON (Strength Fighter, Dex Rogue, Blaster Sorcerer) with level-by-level choices and rationale. Store in a separate collection. Retrieve 1-2 matching templates so the model imitates structure rather than inventing it. **Fastest path to structurally coherent output.**

### 2. Constrained Decoding
GBNF grammar in llama.cpp or guided_json in vLLM to force valid JSON schema. Eliminates malformed output (missing fields, broken JSON) as an entire failure class. Separate from the validator — constrained decoding prevents structural errors, the validator catches semantic ones.

### 3. Deterministic Validator + Repair Loop
Code-based checker reading FoundryVTT JSON for prerequisite chains, proficiency progression, class feat access. Feed validation errors back to LLM: "Your build had these 3 errors, fix only these." Local models are good at targeted fixes even when bad at one-shot generation. Two or three passes gets most of the way there. See memory: `project_build_validation_architecture.md`.

### 4. Build Grammar System Prompt
System prompt encoding PF2e creation order (ancestry → background → class → ability boosts → feats → skills → equipment) with slot counts per level. Forces the model to follow a skeleton rather than free-associating.

### 5. Few-Shot with One Complete Valid Build
One correct level-N build in context pairs well with template collection. Worth more than many retrieved rules chunks for structural correctness.

### 6. Two-Model Pipeline (Planner → Executor → Repairer)
Qwen3-32B in thinking mode picks direction, Qwen2.5-Coder-32B emits JSON, Mistral-Small-24B handles repair passes. More interesting benchmark signal and plays to each model's strengths.

## Retrieval Quality — Medium Impact

These improve what the model sees before generating.

### 7. BM25 Hybrid Retrieval (Reciprocal Rank Fusion)
PF2e is full of exact keyword tokens (press, flourish, rage, focus spell) that dense embeddings blur. Bolt rank_bm25 alongside ChromaDB, fuse results with RRF. ~50 lines of code, couple hours. Second-biggest retrieval win after metadata filtering.

### 8. Query Rewriting / Decomposition
Have the LLM expand a vague request into 3-5 structured sub-queries before retrieval, then union results. "Build me a dwarf fighter" → separate queries for ancestry feats, class feats, equipment. Cheap, high impact.

## Already Implemented or In Progress

- Semantic chunking with structured headers (ingestion plan Phase B)
- Rich metadata filtering — level, category, traits, rarity, action_type (Phase C)
- Separate collections per content type (Phase D)
- mxbai asymmetric query prefix (Phase A)
- Sub-chunking long entries with parent linkage (Phase E)
