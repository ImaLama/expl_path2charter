# Architecture & File Structure

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code / LLM                        │
│                    (asks PF2e rules questions)                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ MCP protocol (stdio)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Server (server/)                        │
│                                                                 │
│  Tools:                                                         │
│   • search_pf2e_rules  — semantic search + metadata filters     │
│   • get_pf2e_entry     — exact name lookup, returns raw JSON    │
│   • list_pf2e_content_types — list available types & collections│
│                                                                 │
│  PF2eDB wrapper:                                                │
│   • Auto-selects embedding model from collection name suffix    │
│   • Translates tool params → ChromaDB where clauses             │
│   • Post-filters traits (ChromaDB $contains workaround)         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│    Ollama Server     │  │      ChromaDB        │
│  (localhost:11434)   │  │  (persistent, local)  │
│                      │  │                       │
│  Embedding models:   │  │  6 collections:       │
│  • nomic-embed-text  │  │  • foundry       (16k)│
│  • mxbai-embed-large │  │  • foundry_mxbai (16k)│
│  • bge-m3            │  │  • foundry_bgem3 (16k)│
│                      │  │  • pf2etools     (11k)│
│  Query-time embed    │  │  • pf2etools_mxbai(11k│
│  via /api/embed      │  │  • pf2etools_bgem3(11k│
└──────────────────────┘  └──────────────────────┘
                                    ▲
                                    │ one-time ingestion
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                   Ingestion Pipeline (ingest/)                  │
│                                                                 │
│  1. Parse JSON files from two data sources                      │
│  2. Clean text (strip HTML / {@tag} markup)                     │
│  3. Generate embeddings via Ollama                              │
│  4. Batch upsert into ChromaDB                                  │
│                                                                 │
│  CLI: python -m ingest.cli --source all --embed-model <model>   │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
mcp-pf2e/
├── requirements.txt            # mcp, chromadb, httpx
├── .mcp.json                   # Claude Code MCP server config (at project root)
│
├── ingest/                     # Data ingestion pipeline
│   ├── __init__.py
│   ├── cli.py                  # CLI entry point (argparse)
│   │                             --source foundry|pf2etools|all
│   │                             --embed-model nomic-embed-text|mxbai-embed-large|bge-m3
│   │                             --categories feats spells ...
│   │                             --wipe --batch-size --db-path --data-dir
│   │
│   ├── foundry_parser.py       # FoundryVTT JSON → PF2eDocument
│   │                             Walks packs/pf2e/{category}/**/*.json
│   │                             One file per game entry
│   │                             Extracts: name, level, traits, prereqs, description
│   │
│   ├── pf2etools_parser.py     # Pf2eTools JSON → PF2eDocument
│   │                             Walks data/{category}/*.json
│   │                             Multiple entries per file (bundled by source book)
│   │                             Handles varying top-level keys (feat, spell, class, etc.)
│   │
│   ├── text_cleaners.py        # Text normalization
│   │                             strip_foundry_html() — removes <p>, @UUID refs, etc.
│   │                             strip_pf2etools_tags() — removes {@spell X}, {@feat Y}
│   │                             flatten_pf2etools_entries() — recursive entry flattener
│   │
│   ├── embeddings.py           # OllamaEmbeddingFunction (ChromaDB-compatible)
│   │                             Per-model context truncation
│   │                             Retry-on-failure with one-by-one fallback
│   │
│   └── loader.py               # ChromaDB batch upsert
│                                 Batch size configurable, upsert for idempotency
│
├── server/                     # MCP server
│   ├── __init__.py
│   ├── main.py                 # Entry point: asyncio + stdio_server
│   ├── tools.py                # Tool definitions (@app.list_tools, @app.call_tool)
│   └── db.py                   # PF2eDB class — ChromaDB wrapper
│                                 Auto-routes to correct embedding model per collection
│                                 Semantic search with metadata filters
│                                 Exact name lookup with raw JSON retrieval
│
└── docs/                       # Documentation
    ├── architecture.md         # This file
    ├── embedding-model-comparison.md  # Benchmark results across 3 models
    └── hybrid-retrieval-qdrant.md     # Future: Qdrant + bge-m3 hybrid plan
```

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
│   └── spells/
│       ├── cantrip/
│       ├── rank-1/ through rank-10/
│       ├── focus/
│       └── rituals/
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
│   ├── feats-crb.json          # All Core Rulebook feats in one file
│   ├── feats-apg.json          # Advanced Player's Guide feats
│   └── ...
├── spells/                     # ~70 files
│   ├── spells-crb.json
│   └── ...
├── class/                      # 32 files (one per class)
│   ├── class-barbarian.json
│   └── ...
├── ancestries/                 # 47 files (one per ancestry)
├── backgrounds/
├── items/
└── ...
```

**JSON schema** (bundled, multiple entries per file):
```json
{
  "feat": [
    {
      "name": "Shield Block",
      "source": "CRB",
      "page": 266,
      "level": 1,
      "traits": ["general"],
      "prerequisites": "{@feat Shield Proficiency}",
      "entries": [
        "You snap your shield in place to ward off a blow...",
        { "type": "list", "items": ["Item 1", "Item 2"] }
      ]
    },
    ...
  ]
}
```

## Normalized Document Model

Both parsers produce the same `PF2eDocument` dataclass:

```python
PF2eDocument(
    id="foundry_abc123",        # Prefixed to avoid cross-source collisions
    name="Shield Block",
    content_type="feat",        # feat, spell, class, ancestry, equipment, etc.
    level=1,
    traits=["general"],
    prerequisites="trained in Athletics",
    source_book="Player Core",
    rarity="common",
    text="Shield Block (feat, level 1). Traits: general. ...",  # For embedding
    raw_json="{...}",           # Original JSON for exact lookups
)
```

The `text` field concatenates name, type, level, traits, prerequisites,
description (cleaned), and rules keys — optimized for semantic search.

## ChromaDB Storage

```
_state/vector_db/pf2e_chroma/
└── (ChromaDB internal files)

Collections:
  foundry          — 16,177 docs — nomic-embed-text (768-dim)
  foundry_mxbai    — 16,177 docs — mxbai-embed-large (1024-dim)
  foundry_bgem3    — 16,177 docs — bge-m3 dense-only (1024-dim)
  pf2etools        — 11,471 docs — nomic-embed-text (768-dim)
  pf2etools_mxbai  — 11,471 docs — mxbai-embed-large (1024-dim)
  pf2etools_bgem3  — 11,471 docs — bge-m3 dense-only (1024-dim)
```

Each document stored with metadata fields: `name`, `content_type`, `level`,
`traits` (comma-separated), `prerequisites`, `source_book`, `rarity`, `raw_json`.

## Query Flow

```
User asks: "What feats improve shield blocking?"
                    │
                    ▼
         MCP tool: search_pf2e_rules
         {query: "feats improve shield blocking",
          content_type: "feat", source: "foundry_mxbai"}
                    │
                    ▼
         PF2eDB.search()
           1. Build ChromaDB where clause: {content_type: "feat"}
           2. Select embedding model from collection suffix → mxbai-embed-large
           3. Embed query via Ollama /api/embed
           4. ChromaDB vector search (cosine similarity)
           5. Post-filter by traits if requested
           6. Return top-N with metadata + relevance scores
                    │
                    ▼
         JSON response to LLM:
         [{"name": "Shield Block", "level": 1, "relevance_score": 0.82, ...},
          {"name": "Shield Warden", "level": 6, ...}, ...]
```
