# Feat: LoRA Fine-Tuning for PF2e Fluency

**Status:** Planned (future — defer until RAG pipeline is solid)
**Priority:** Low — only pursue if RAG + re-ranker still show terminology gaps
**Depends on:** RAG-augmented generation, re-ranker, evaluation baseline

## Problem

Even with good RAG retrieval, local models may struggle with PF2e-specific
terminology, action economy concepts, and the structured format of character
builds. They may misinterpret retrieved rules or fail to apply them correctly
because they lack foundational understanding of the game system.

## Approaches

### A) LoRA (Low-Rank Adaptation) — Recommended

Train a small adapter on top of frozen base weights. The model learns PF2e
vocabulary and reasoning patterns without losing general capabilities.

**Training data:** Generate Q&A pairs from the rules corpus:
- "What action cost does Exploit Vulnerability have?" -> "One action..."
- "List the Thaumaturge class feats available at level 4" -> structured list
- "What traits does the Esoteric Antithesis feat have?" -> "Esoteric, Thaumaturge"
- Character build examples with correct feat chains

**Tools:**
- [Unsloth](https://github.com/unslothai/unsloth) — fast, memory-efficient,
  runs well on RTX 3090. Recommended for this hardware.
- [Axolotl](https://github.com/OpenAccess-AI-Collective/axolotl) — more
  flexible config, good for experimentation.

**Hardware fit:**
- Dual RTX 3090 (48GB total VRAM) can train LoRA on models up to ~32B
- 70B models would need QLoRA (quantized LoRA) — feasible but slower
- Training time: hours to a day depending on dataset size

**Estimated dataset:**
- ~5,000-10,000 Q&A pairs generated from the 27K ChromaDB documents
- Could use a strong cloud model (Gemini, Claude) to generate training pairs
  from raw rule text — meta-use of the eval framework

### B) Ollama Modelfile with System Prompt — Quick Win

Bake a condensed rules summary into the model's default system prompt:

```
FROM llama3.3-8k
SYSTEM """You are a Pathfinder 2e rules assistant.

Key mechanics:
- Three-action economy: each turn has 3 actions
- MAP: -5/-10 on 2nd/3rd attacks
- Proficiency = level + proficiency bonus (trained +2, expert +4, master +6, legendary +8)
- [more condensed rules...]
"""
```

**Limitations:**
- Eats into the 8K context window (2-3K tokens of always-on context)
- Can't fit specific feat details — too many feats
- Better suited for general mechanics grounding, not specific rule lookups

**Recommendation:** Do this regardless — it's 10 minutes of work and helps
even with RAG. Keep it to ~1K tokens of core mechanics.

### C) Hybrid: LoRA + RAG — Best of Both Worlds

Fine-tune for general PF2e fluency (terminology, action economy, character
build structure), keep RAG for specific rule lookups.

The model stops hallucinating feat names because it has seen real ones during
training. RAG handles precise mechanical details like action costs and prerequisites.

## Decision Framework

```
Is RAG + re-ranker + strict prompt sufficient?
├── Yes → Don't fine-tune. Ship it.
└── No → What's failing?
    ├── Terminology confusion → LoRA on Q&A pairs
    ├── Format/structure issues → LoRA on build examples
    ├── Specific rule errors → Improve RAG retrieval
    └── All of the above → Hybrid (LoRA + RAG)
```

## Training Data Generation Plan

1. Export all feats/spells/classes from ChromaDB
2. Use a cloud model to generate Q&A pairs:
   - Factual questions ("What does X do?")
   - Comparative questions ("How does X differ from Y?")
   - Build questions ("What feats synergize with X?")
   - Rules interaction questions ("Can I use X and Y in the same turn?")
3. Validate generated pairs against source documents
4. Format as instruction-following dataset (Alpaca/ShareGPT format)
5. Train LoRA adapter
6. Export to GGUF for Ollama consumption

## Verification

- Before/after comparison on the standard pf2e eval pack
- Measure hallucination rate (auto_scorer fabrication check)
- Compare LoRA model vs base model both with and without RAG
- Ensure general capability isn't degraded (run starter pack too)

## Risks

- Training data quality is critical — garbage in, garbage out
- Overfitting to training set phrasing — test with diverse query styles
- Rules errata invalidates baked-in knowledge — need retraining pipeline
- Quantization of LoRA adapter may lose quality — test GGUF export carefully
