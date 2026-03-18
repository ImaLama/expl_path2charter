"""MCP tool definitions for PF2e rules search."""

import json

from mcp.server import Server
from mcp.types import Tool, TextContent

from .db import PF2eDB


def register_tools(app: Server, db: PF2eDB):
    """Register all PF2e tools on the MCP server."""

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_pf2e_rules",
                description=(
                    "Search Pathfinder 2e rules, feats, spells, classes, ancestries, "
                    "equipment, and other game content using semantic search. "
                    "Returns the most relevant entries matching your query."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query (e.g., 'feats that improve shield blocking')",
                        },
                        "content_type": {
                            "type": "string",
                            "description": "Filter by content type",
                            "enum": [
                                "feat", "spell", "class", "class-feature",
                                "ancestry", "ancestry-feature", "heritage",
                                "background", "equipment", "action",
                                "condition", "deity", "archetype",
                            ],
                        },
                        "level_min": {
                            "type": "integer",
                            "description": "Minimum level filter",
                        },
                        "level_max": {
                            "type": "integer",
                            "description": "Maximum level filter",
                        },
                        "traits": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required traits (AND logic, e.g., ['monk', 'ki'])",
                        },
                        "source": {
                            "type": "string",
                            "enum": [
                                "foundry", "pf2etools",
                                "foundry_nomic", "pf2etools_nomic",
                                "foundry_mxbai", "pf2etools_mxbai",
                                "foundry_bgem3", "pf2etools_bgem3",
                            ],
                            "default": "foundry",
                            "description": "Collection to search. 'foundry'/'pf2etools' are nomic-embed-text. Suffixed variants use different embedding models for comparison.",
                        },
                        "n_results": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of results (max 20)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_pf2e_entry",
                description=(
                    "Get the full details of a specific PF2e game entry by exact name. "
                    "Returns the complete raw JSON data for the entry."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact name of the entry (e.g., 'Shield Block', 'Fireball')",
                        },
                        "content_type": {
                            "type": "string",
                            "description": "Narrow search to specific content type",
                        },
                        "source": {
                            "type": "string",
                            "enum": [
                                "foundry", "pf2etools",
                                "foundry_nomic", "pf2etools_nomic",
                                "foundry_mxbai", "pf2etools_mxbai",
                                "foundry_bgem3", "pf2etools_bgem3",
                            ],
                            "default": "foundry",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="list_pf2e_content_types",
                description=(
                    "List all available content types in the PF2e database "
                    "(feat, spell, class, ancestry, etc.) and collection info."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": [
                                "foundry", "pf2etools",
                                "foundry_nomic", "pf2etools_nomic",
                                "foundry_mxbai", "pf2etools_mxbai",
                                "foundry_bgem3", "pf2etools_bgem3",
                            ],
                            "default": "foundry",
                        },
                    },
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_pf2e_rules":
            results = db.search(
                query=arguments["query"],
                source=arguments.get("source", "foundry"),
                content_type=arguments.get("content_type"),
                level_min=arguments.get("level_min"),
                level_max=arguments.get("level_max"),
                traits=arguments.get("traits"),
                n_results=arguments.get("n_results", 5),
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_pf2e_entry":
            entry = db.get_entry(
                name=arguments["name"],
                source=arguments.get("source", "foundry"),
                content_type=arguments.get("content_type"),
            )
            if entry:
                return [TextContent(type="text", text=json.dumps(entry, indent=2))]
            return [TextContent(type="text", text=f"No entry found with name: {arguments['name']}")]

        elif name == "list_pf2e_content_types":
            source = arguments.get("source", "foundry")
            try:
                types = db.list_content_types(source)
                collections = db.list_collections()
                result = {
                    "source": source,
                    "content_types": types,
                    "collections": collections,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {e}")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
