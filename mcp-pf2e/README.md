# PF2e Rules MCP Server

An MCP (Model Context Protocol) server that gives LLMs access to a local
Pathfinder 2e rules database. Ingests JSON data from two community sources,
embeds it into ChromaDB with multiple embedding models, and exposes semantic
search via MCP tools.

## What It Does

- Parses 27,648 PF2e game entries (feats, spells, classes, ancestries,
  equipment, etc.) from FoundryVTT and Pf2eTools repositories
- Stores them in ChromaDB with cosine-similarity vector search
- Supports 3 embedding models (nomic-embed-text, mxbai-embed-large, bge-m3)
  in separate collections for A/B comparison
- Serves an MCP server that Claude Code (or any MCP client) can connect to
  for rule lookups, feat searches, and build verification

## Quick Start

### Prerequisites

- Python 3.12+ with venv
- [Ollama](https://ollama.ai) running locally
- PF2e data at `../_state/static_data/pf2/` (FoundryVTT + Pf2eTools repos)

### Setup

```bash
# Create and activate venv
python -m venv ~/venv
source ~/venv/bin/activate

# Install dependencies
pip install mcp chromadb httpx

# Pull embedding models
ollama pull nomic-embed-text
ollama pull mxbai-embed-large   # recommended — best retrieval quality
ollama pull bge-m3              # optional
```

### Ingest Data

```bash
cd /home/labrat/projects/path2charter/mcp-pf2e

# Ingest with mxbai (recommended)
python -m ingest.cli --source all --embed-model mxbai-embed-large

# Or with nomic (faster, slightly less accurate)
python -m ingest.cli --source all --embed-model nomic-embed-text

# Ingest only specific categories
python -m ingest.cli --source foundry --embed-model mxbai-embed-large --categories feats spells

# Re-ingest from scratch
python -m ingest.cli --source all --embed-model mxbai-embed-large --wipe
```

### Connect to Claude Code

The `.mcp.json` at the project root configures the MCP server automatically.
Restart Claude Code after first setup to pick up the config:

```json
{
  "mcpServers": {
    "pf2e-rules": {
      "command": "/home/labrat/venv/bin/python",
      "args": ["-m", "server.main"],
      "cwd": "/home/labrat/projects/path2charter/mcp-pf2e"
    }
  }
}
```

## MCP Tools

### `search_pf2e_rules`

Semantic search across PF2e game content.

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string (required) | Natural language search query |
| `content_type` | string | Filter: feat, spell, class, ancestry, equipment, etc. |
| `level_min` | int | Minimum level |
| `level_max` | int | Maximum level |
| `traits` | string[] | Required traits (AND logic) |
| `source` | string | Collection: foundry, foundry_mxbai, pf2etools, etc. |
| `n_results` | int | Number of results (default 5, max 20) |

### `get_pf2e_entry`

Exact name lookup returning full raw JSON for a specific entry.

### `list_pf2e_content_types`

Lists available content types and collection statistics.

## Collections

| Collection | Documents | Model | Quality |
|-----------|-----------|-------|---------|
| `foundry_mxbai` | 16,177 | mxbai-embed-large | Best |
| `foundry` | 16,177 | nomic-embed-text | Good |
| `foundry_bgem3` | 16,177 | bge-m3 (dense only) | Fair |
| `pf2etools_mxbai` | 11,471 | mxbai-embed-large | Best |
| `pf2etools` | 11,471 | nomic-embed-text | Good |
| `pf2etools_bgem3` | 11,471 | bge-m3 (dense only) | Fair |

See [docs/embedding-model-comparison.md](docs/embedding-model-comparison.md)
for detailed benchmarks.

## Documentation

- [Architecture & File Structure](docs/architecture.md) — system diagrams, data schemas, query flow
- [Embedding Model Comparison](docs/embedding-model-comparison.md) — benchmark results across 3 models
- [Hybrid Retrieval Plan](docs/hybrid-retrieval-qdrant.md) — future Qdrant + bge-m3 sparse/ColBERT plan
