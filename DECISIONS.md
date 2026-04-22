# Architectural Decisions & Design Principles

This document captures key decisions made during architect review sessions. Claude Code should treat these as settled unless explicitly revisited.

---

## Project Architecture

### Four-Layer Game AI Model
Every game AI system decomposes into four layers. This project follows this structure:

- **Layer 1 — Ontology (data):** Structured PF2e game objects from foundryvtt/pf2e repo. Served via `static_reader.py` filesystem lookups. Machine-readable, not LLM-readable.
- **Layer 2 — Mechanics (code):** Deterministic rules — validation, prerequisite checking, slot counting, ability score bounds. All in `validator/`. Never delegate to LLM.
- **Layer 3 — Strategy (LLM):** Feat selection, build optimization, synergy reasoning. LLM operates on pre-computed facts and constrained enums, not raw rules text.
- **Layer 4 — Context (LLM):** Natural language understanding of user intent, flavor descriptions, thematic choices. Pure LLM territory.

**Key principle:** Information flows down (intent → strategy → mechanics → data) and back up (data → computed results → evaluation → recommendation). LLM handles layers 3-4, code handles layers 1-2. The interface between them is structured data with computed values — never raw prose the LLM must interpret numerically.

### Two-Pass Build Pipeline
The pipeline uses two LLM passes, not one:

1. **Skeleton pass (creative):** Concept → class, ancestry, heritage, background, level. Temperature 0.7. Schema-constrained with class/ancestry/background enums.
2. **Generation pass (structured):** Skeleton + decomposed feat options → full build JSON. Temperature 0.5. Fully enum-constrained via JSON schema. All feat slots required.

Rationale: Separating creative interpretation from structured selection lets each pass optimize for its task. The skeleton pass is where the LLM adds value creatively. The generation pass is mechanical menu selection.

### No Mandatory CLI Parameters
All CLI parameters are optional. A bare concept description like "a character who casts spells up close, ideally hidden" is a valid input. The skeleton pass resolves class/ancestry/level from the concept. If the user specifies some parameters, the skeleton pass fills in the rest.

---

## Vector DB Role

### ChromaDB Is Not in the Critical Build Path
The pipeline evolved so that `static_reader` + enum constraints handle everything the vector DB used to do. The validator was decoupled from ChromaDB (Track A, completed). Builds run without any embedding model loaded — no VRAM cost.

### ChromaDB Is Retained for Enhancement & Learning
The vector DB remains valuable for:
1. **Concept-to-feat relevance ranking** — embed flavor description, rank valid feats by semantic similarity, present top-N with descriptions in prompt (rest as names only)
2. **Synergy detection** — given picked feats, find semantically related feats at later levels
3. **Post-build gap analysis** — surface high-relevance feats the model didn't pick
4. **Build archetype discovery** — cross-collection search to inform skeleton pass class selection
5. **RAG learning vehicle** — practicing retrieval patterns that transfer to other domains

### Phase 1: Concept-to-Feat Ranking (Implemented)
Embed concept once via mxbai, fetch pre-stored feat embeddings from ChromaDB via `collection.get($in)`, compute cosine similarity with numpy. Top 10 class feats, top 5 others get full descriptions in prompt. Prerequisite chain members always included. Controlled by `use_vector_ranking` config flag.

### Phase 2: Skeleton-Informing via Cross-Collection Search (Future)
Before the skeleton pass, embed the concept and search across all collections (feats, class features, spells, equipment). Aggregate which class/ancestry appears most in top results. Feed this evidence into the skeleton prompt to improve class/ancestry selection.

### Phase 3: Prerequisite Dependency Chain Analysis (Future)
Present feat choices as paths, not isolated picks: "Rebounding Toss (lvl 1) → Knockdown (lvl 4, needs Athletics) → Improved Knockdown (lvl 10)." Helps the model understand downstream consequences of feat picks. Build a DAG from prerequisite data, find chains that include ranked feats, present as ordered paths.

### Vector DB Settings (When Used)
- Embedding model: `mxbai-embed-large` via Ollama
- Distance metric: Cosine (matches mxbai training)
- Query prefix: `"Represent this sentence for searching relevant passages: "` — query-side only, never at ingestion
- Chunking: One game object = one chunk, with structured header prefix
- Long entries (>400 tokens): Split into sub-chunks with `parent_id` metadata
- Metadata fields: type, name, level, class, traits, rarity, source, has_prerequisites
- Always filter by metadata before vector similarity

---

## Schema Enforcement

### JSON Schema Enums Eliminate Hallucination
Ollama's `response_format` with `json_schema` and enum constraints prevents the model from emitting non-existent feat names. This solved the D&D hallucination problem ("Improved Critical", "Precise Shot") completely.

### Enum Strategy: Two-Tier
- **Full enum enforcement** for all feat slots: ancestry, general, skill, and class feats
- **Class feat enums include ALL dedication feats** (~186 at level 2) so the model can spontaneously pick any archetype without pre-specifying it
- Heritage and background also enum-constrained in the appropriate pass

### Thinking Models Need Higher Token Budget
Qwen3's thinking mode consumes hidden tokens against `max_tokens`. Generation uses 4096 tokens for thinking models, 2048 for non-thinking. Repair uses 2048/1024 respectively. The `THINKING_MODELS` set tracks which models need this.

### Schema Is Cached Across Repair Iterations
`build_response_schema()` is called once per build, stored, and reused for all repair passes. The schema depends only on `BuildOptions` which don't change during repair.

---

## Validator Design

### Filesystem-Based Feat Index
The validator uses `get_feat_data(feat_name)` which builds a `{name_lower: filepath}` index across all 5,975 feat JSON files on first call, cached via `@lru_cache(1)`. This replaced all ChromaDB `db.get_entry()` lookups — no embedding model, no VRAM cost, instant lookups. The index also falls back to slugified names for fuzzy matching.

### 14 Rule Functions
The validator runs deterministic checks — never LLM judgment. Current rules:
1. `check_duplicate_feats` — most feats can only be taken once
2. `check_feat_existence` — verifies against filesystem index; also emits rarity warnings for uncommon/rare/unique feats (GM permission needed)
3. `check_level_legality` — feat level ≤ character level at slot
4. `check_slot_counts` — correct number of feats per slot type
5. `check_feat_slot_type` — right category in right slot
6. `check_class_feat_access` — class feats match character's class
7. `check_ancestry_feat_access` — ancestry feats match character's ancestry
8. `check_heritage` — heritage exists for chosen ancestry
9. `check_background` — background exists in data
10. `check_skill_ranks` — skill proficiency doesn't exceed level thresholds (expert 3+, master 7+, legendary 15+)
11. `check_skill_counts` — correct number of trained skills for class + int modifier + background
12. `check_ability_scores` — bounds check: no odd scores, no score above max achievable at level, key ability ≥ 14, total boosts plausible
13. `check_prerequisites` — feat/ability/proficiency prereqs met
14. `check_archetype_rules` — 2nd dedication needs 2 non-dedication archetype feats first

### Planned Additions
- Equipment existence + budget validation (when equipment system is built)

### Known Failure Pattern: Skill Feat Prerequisites
The dominant validation failure mode is models picking skill feats that require proficiency the build doesn't have (e.g., "Powerful Leap" requires expert Athletics, "Steady Balance" requires trained Acrobatics). This happens because enum constraints guarantee the feat *exists* but not that its *prerequisites* are met. The repair loop often cycles through multiple invalid skill feats. Potential mitigation: pre-filter skill feat enums by prerequisite satisfaction, not just by trained skill list.

### Class Feature Prerequisites
Prerequisites are checked against both chosen feats AND auto-granted class features (via `get_class_features()`). Example: "Esoteric Warden" requires "Exploit Vulnerability" which every thaumaturge gets at level 1 — this is a class feature, not a feat choice.

### Repair Loop
- Max 2 repair attempts by default
- Repair temperature lower than generation (0.5 vs 0.7, or lower with schema)
- Repair prompts accumulate history of failed substitutions with explicit blocklist to prevent circular attempts ("Deceit" → "Deception" → "Deceit")
- Repair prompts include the valid options list for the failing slot

---

## Model Selection

### Current Primary: Qwen3-32B
Works but has thinking-mode overhead with constrained decoding. Hidden thinking tokens consume ~50% of token budget on enum-constrained tasks where thinking adds minimal value.

### Recommended Comparison Models
- **Qwen2.5-Coder-32B-Instruct** — primary alternative. Coder tunes treat structured output as typed data. No thinking overhead. Expected to match or beat Qwen3 on constrained JSON tasks.
- **Mistral-Small-3.2-24B** — candidate for repair pass (fast, smaller, strong instruction following) and as neutral benchmark judge model
- Skip: Llama-3.3-70B (slow on pipeline parallelism), DeepSeek-R1-Distill (long reasoning traces, expensive)

### Split Pipeline (Future)
- Planner (creative): Qwen3-32B in thinking mode for skeleton pass
- Executor (structured): Qwen2.5-Coder-32B with schema for generation pass
- Repairer (fast): Mistral-Small-3.2 for targeted fixes

---

## Benchmarking

### Single Unified System
One benchmark system in `mcp-pf2e/benchmarks/`. The old `llm-eval/` is dormant (`llm-eval_dormant/`). No parallel evaluation systems.

### Cases × Configs Matrix
- `suite.json` contains fixed test cases (what to build) and run configs (how to build it)
- Runner does cross product: every case × every selected config
- Results in append-only JSONL — one line per case per run
- `--configs` and `--cases` flags for filtering
- Run configs may include future parameters not yet supported by the pipeline; these are flagged as unsupported in output but don't block execution

### Metrics Per Run
- Valid (boolean), attempts, error types
- Timings per step (skeleton, decompose, generate, validate, each repair)
- Token usage (prompt, completion, total)
- `model_is_thinking` boolean flag — tracks whether generator uses thinking tokens, rather than parsing thinking tokens separately. Cost comparison between thinking/non-thinking models on same cases makes the overhead obvious.
- Theme score (1-10, LLM-as-judge): does the build match the concept?
- Synergy score (1-10, LLM-as-judge): do choices work together mechanically?
- Evaluator notes (LLM-generated text explaining scores)
- Human feedback (empty by default, filled manually)

### Judge Model Must Differ from Generator
Self-evaluation bias is real. Use a different model for judging than the one being benchmarked. Default: Mistral-Small-3.2 as neutral judge for all runs.

---

## Performance Principles

### VRAM Management
- Unload embedding model (mxbai) before loading generation model
- Validator uses no embeddings — pure filesystem lookups via `get_feat_data()`
- One model load per benchmark config, not per case
- Generator unloaded before loading judge model between pipeline and evaluation

### Prompt Efficiency
- Enum-constrained slots use names only (no descriptions) — schema enforces validity
- Full descriptions only for class feats where thematic reasoning matters
- `max_tokens` reduced: 2048 generation / 1024 repair (non-thinking models)

### Caching
- `static_reader.py` functions use `@lru_cache` — filesystem is read once per session
- `_build_feat_index()` scans all 5,975 feats on first call, cached with `@lru_cache(1)`
- Known bug: `get_class_features(class_name, max_level)` cache may return stale data when called with different `max_level` values across benchmark runs
- `_REPEATABLE_FEATS` is a hardcoded set — should be read from feat data (`system.traits` or `system.maxTakable` field) to avoid false positives

---

## Development Principles

### Never Build Two Untested Layers Simultaneously
Test each layer independently before combining. The MCP server, ingestion pipeline, validator, and orchestrator were each verified in isolation.

### Bias Toward Principles, Not Specific Choices
Templates teach format, not content. The build grammar encodes slot structure, not "always take Power Attack." Bias toward synergy and prereq chains, not specific feat combinations.

### Deterministic Validation > LLM Judgment for Hard Rules
If a rule can be checked with code (prereqs, slot counts, level gates), it must be. LLM judgment is reserved for subjective quality assessment (theme score, synergy score) — never for rules enforcement.

### Filter Before Search, Constrain Before Generate
Metadata filtering before vector similarity. Enum constraints before LLM generation. The earlier you eliminate invalid options, the less work the LLM and validator have to do.

---

## Known Technical Debt

- `_REPEATABLE_FEATS` hardcoded set — should read from feat data
- Cross-project imports via `sys.path` manipulation (orchestrator, benchmarks)
- Equipment not yet validated (prices, existence, proficiency requirements)
- Spell prerequisites ("ability to cast spells") always pass — deferred as rare
- Sub-choices within feats ("Basic Devotion" → pick a champion feat) not captured in schema
- Free Archetype variant rule not supported in slot generation
- Skill feat enum includes feats whose prerequisites can't be met by the build — causes the most common validation failure (see "Known Failure Pattern" above)
