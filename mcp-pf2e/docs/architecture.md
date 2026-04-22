# Architecture & File Structure

## Overview

The system has two main flows: a **build pipeline** (generates validated PF2e character builds via local LLMs) and an **MCP server** (answers rules questions via semantic search). Both read from the same static data and ChromaDB.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Build Pipeline (orchestrator/)                    │
│                                                                      │
│  CLI / Benchmark Runner                                              │
│       │                                                              │
│       ▼                                                              │
│  Skeleton Pass ──► Decomposer ──► Generation ──► Validator ──► Repair│
│  (concept→class)   (enum options)  (Ollama LLM)  (14 rules)   loop  │
│       │                │                              │              │
│       ▼                ▼                              ▼              │
│  Schema-constrained   Static Reader            get_feat_data()       │
│  class/ancestry enum  (filesystem)             (feat index, cached)  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ reads
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│              Static Data (_state/static_data/pf2/pf2e/)              │
│                                                                      │
│  5,975 feats · 27 classes · 50 ancestries · 490 backgrounds          │
│  1,796 spells · 5,616 equipment · heritages · class-features         │
└──────────────────────────────────────────────────────────────────────┘
                           ▲
                           │ also reads (for embedding search)
┌──────────────────────────┴───────────────────────────────────────────┐
│                     MCP Server (server/)                              │
│                                                                      │
│  Tools:                                                              │
│   • search_pf2e_rules  — semantic search + metadata filters          │
│   • get_pf2e_entry     — exact name lookup, returns raw JSON         │
│   • list_pf2e_content_types — available types & collections          │
│   • get_build_options  — decompose build into feat options            │
│                                                                      │
│  PF2eDB wrapper → ChromaDB (6 collections, 3 embedding models)       │
└──────────────────────────────────────────────────────────────────────┘
```

## File Structure

```
mcp-pf2e/
├── requirements.txt
├── .mcp.json                   # Claude Code MCP server config (at project root)
│
├── orchestrator/               # Build generation pipeline
│   ├── __init__.py
│   ├── cli.py                  # CLI: --request, --class, --level, --ancestry, --dedications
│   ├── pipeline.py             # run_build(): skeleton → decompose → generate → validate → repair
│   └── prompt_builder.py       # System/user prompts, JSON schema with enum constraints
│
├── query/                      # Data access layer
│   ├── __init__.py
│   ├── types.py                # BuildSpec, BuildOptions, FeatSlot, SlotOptions, FeatOption
│   ├── decomposer.py           # Enumerates all valid feat options per slot
│   └── static_reader.py        # Filesystem-based lookups, @lru_cache, feat index
│
├── validator/                  # Deterministic rule checking
│   ├── __init__.py
│   ├── types.py                # ParsedBuild, ValidationError, ValidationResult
│   ├── parser.py               # Regex extraction of builds from free-text
│   ├── engine.py               # BuildValidator: orchestrates 14 rules
│   ├── rules.py                # 14 rule functions (feat existence, prereqs, slots, etc.)
│   ├── prerequisite.py         # Prerequisite parsing and checking
│   └── repair.py               # Format validation errors into repair prompts
│
├── benchmarks/                 # Pipeline benchmarking
│   ├── __init__.py
│   ├── suite.json              # Fixed test cases + run configs (versioned)
│   ├── runner.py               # CLI: cases × configs matrix, JSONL output
│   ├── evaluator.py            # LLM-as-judge (theme + synergy scoring)
│   ├── report.py               # list/show/compare from JSONL results
│   └── .gitignore              # results.jsonl excluded from git
│
├── builds/                     # Saved build outputs (examples/reference)
│
├── ingest/                     # Data ingestion pipeline (ChromaDB)
│   ├── __init__.py
│   ├── cli.py                  # CLI: --source, --embed-model, --categories, --wipe
│   ├── foundry_parser.py       # FoundryVTT JSON → PF2eDocument
│   ├── pf2etools_parser.py     # Pf2eTools JSON → PF2eDocument
│   ├── text_cleaners.py        # HTML/tag stripping
│   ├── embeddings.py           # OllamaEmbeddingFunction (ChromaDB-compatible)
│   └── loader.py               # ChromaDB batch upsert
│
├── server/                     # MCP server
│   ├── __init__.py
│   ├── main.py                 # Entry point: asyncio + stdio_server
│   ├── tools.py                # 4 MCP tool definitions
│   └── db.py                   # PF2eDB class — ChromaDB wrapper
│
└── docs/
    ├── architecture.md         # This file
    ├── embedding-model-comparison.md
    ├── future-improvements.md
    └── hybrid-retrieval-qdrant.md
```

## Build Pipeline Flow

```
User: "a sneaky caster who fights up close"
                    │
                    ▼
         ┌─ Skeleton Pass (optional) ─┐
         │  LLM picks class/ancestry/ │
         │  heritage/background/level │
         │  Schema: class + ancestry  │
         │  enums from filesystem     │
         └────────────┬───────────────┘
                      │ class=magus, ancestry=gnome, level=5
                      ▼
         ┌─ Decomposer ──────────────┐
         │  Enumerates ALL valid      │
         │  feat options per slot     │
         │  from filesystem           │
         │  (class/ancestry/general/  │
         │   skill/archetype feats)   │
         └────────────┬───────────────┘
                      │ BuildOptions: 8 slots, ~800 options
                      ▼
         ┌─ Prompt + Schema Builder ──┐
         │  System prompt (rules)     │
         │  User prompt (options)     │
         │  JSON schema with enum     │
         │  constraints per slot      │
         └────────────┬───────────────┘
                      │
                      ▼
         ┌─ Generation (Ollama) ──────┐
         │  Model: qwen3:32b          │
         │  Temperature: 0.5          │
         │  JSON schema enforced      │
         │  → Can only emit valid     │
         │    feat names (enums)      │
         └────────────┬───────────────┘
                      │ build JSON
                      ▼
         ┌─ Validator (14 rules) ─────┐
         │  Feat existence, prereqs,  │
         │  slot counts, level gates, │
         │  class/ancestry access,    │
         │  ability scores, skills    │
         └────────────┬───────────────┘
                      │
              ┌───────┴───────┐
              │ valid?        │
              ▼               ▼
           DONE         Repair Loop (max 2)
                        │  - Narrows skill feat
                        │    enums to match actual
                        │    trained skills
                        │  - Lists valid alternatives
                        │  - Accumulates error history
                        └──► re-validate ──► DONE or FAIL
```

## Key Design Decisions

### Enum Constraints Eliminate Hallucination
Ollama's `response_format` with `json_schema` prevents the model from emitting non-existent names. Every feat slot is constrained to an enum of valid options loaded from the filesystem.

### Validator Uses Filesystem, Not ChromaDB
`get_feat_data(feat_name)` builds a `{name_lower: filepath}` index of 5,975 feats on first call (cached). All 14 validator rules use this — no embedding model, no VRAM cost.

### Repair Narrows Schema Dynamically
On repair passes, skill feat enums are rebuilt based on the character's actual trained skills (extracted from the failed build JSON). The schema is deep-copied and narrowed — the original stays intact.

### Two-Pass Architecture
Skeleton pass (creative) → Generation pass (structured). Separating concept interpretation from menu selection lets each optimize for its task.

See `DECISIONS.md` at project root for the full rationale.

## Data Sources

### Source 1: FoundryVTT (`_state/static_data/pf2/pf2e/`)

The official Pathfinder 2e system for Foundry Virtual Tabletop.

```
pf2e/packs/pf2e/
├── feats/                      # 5,861 files
│   ├── ancestry/
│   │   ├── dwarf/
│   │   │   ├── level-1/
│   │   │   │   ├── dwarven-lore.json
│   │   │   │   └── ...
│   │   │   ├── level-5/
│   │   │   └── ...
│   │   ├── elf/
│   │   └── ...
│   ├── class/
│   │   ├── barbarian/
│   │   ├── fighter/
│   │   └── ...
│   ├── general/
│   ├── skill/
│   └── archetype/
├── classes/                    # 27 files (one per class)
├── class-features/             # 841 files
├── ancestries/                 # 50 files
├── ancestry-features/          # 55 files
├── heritages/                  # 321 files
├── backgrounds/                # 490 files
├── spells/                     # 1,796 files
├── equipment/                  # 5,616 files
├── actions/                    # 546 files
├── conditions/                 # 43 files
├── deities/                    # 478 files
└── hazards/                    # 53 files
```

**JSON schema** (per entry):
```json
{
  "_id": "unique-id",
  "name": "Shield Block",
  "type": "feat",
  "system": {
    "level": { "value": 1 },
    "traits": { "rarity": "common", "value": ["general"] },
    "prerequisites": { "value": [{ "value": "trained in Athletics" }] },
    "description": { "value": "<p>HTML description...</p>" },
    "publication": { "title": "Player Core", "remaster": true },
    "rules": [
      { "key": "FlatModifier", "selector": "ac", "value": 2 }
    ]
  }
}
```

### Source 2: Pf2eTools (`_state/static_data/pf2/Pf2eTools/`)

Data powering the pf2etools.com community reference site.

```
Pf2eTools/data/
├── feats/                      # ~70 files (bundled by source book)
│   ├── feats-crb.json
│   └── ...
├── spells/
├── class/
├── ancestries/
├── backgrounds/
├── items/
└── ...
```

## ChromaDB Storage

```
_state/vector_db/pf2e_chroma/

Collections:
  foundry          — 16,177 docs — nomic-embed-text (768-dim)
  foundry_mxbai    — 16,177 docs — mxbai-embed-large (1024-dim)
  foundry_bgem3    — 16,177 docs — bge-m3 dense-only (1024-dim)
  pf2etools        — 11,471 docs — nomic-embed-text (768-dim)
  pf2etools_mxbai  — 11,471 docs — mxbai-embed-large (1024-dim)
  pf2etools_bgem3  — 11,471 docs — bge-m3 dense-only (1024-dim)
```

ChromaDB is used by the MCP server for semantic search. The build pipeline does NOT use ChromaDB — it reads directly from the filesystem via `static_reader.py`.

## Normalized Document Model

Both parsers produce the same `PF2eDocument` dataclass:

```python
PF2eDocument(
    id="foundry_abc123",
    name="Shield Block",
    content_type="feat",
    level=1,
    traits=["general"],
    prerequisites="trained in Athletics",
    source_book="Player Core",
    rarity="common",
    text="Shield Block (feat, level 1). Traits: general. ...",
    raw_json="{...}",
)
```

## Benchmarking

The benchmark system in `benchmarks/` runs fixed test cases through the pipeline with varying model/config combinations:

```bash
# Run all cases with one config
python -m benchmarks.runner --configs qwen3-schema-on

# Run specific cases
python -m benchmarks.runner --cases simple-fighter thrown-fighter

# View results
python -m benchmarks.report list
python -m benchmarks.report show 2026-04-22_001
python -m benchmarks.report compare 2026-04-22_001
```

Results are stored as append-only JSONL with per-case timings, token usage, validation results, and LLM-as-judge theme/synergy scores.
