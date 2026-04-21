"""MCP tool definitions for PF2e rules search."""

import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).parent.parent))

from .db import PF2eDB
from query.decomposer import get_build_options


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
                    "Returns the most relevant entries matching your query. "
                    "Searches per-type collections (feats, spells, etc.) — "
                    "specify content_type to target a specific collection."
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
                            "description": "Filter by content type (also selects the collection to search)",
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
                        "category": {
                            "type": "string",
                            "enum": ["ancestry", "class", "skill", "general", "archetype", "classfeature"],
                            "description": "Feat/feature category filter",
                        },
                        "action_type": {
                            "type": "string",
                            "enum": ["passive", "action", "reaction", "free"],
                            "description": "Filter by action type",
                        },
                        "source": {
                            "type": "string",
                            "description": "Legacy: literal collection name override. Prefer content_type instead.",
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
                            "description": "Narrow search to specific content type / collection",
                        },
                        "source": {
                            "type": "string",
                            "description": "Legacy: literal collection name override. Prefer content_type instead.",
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
                            "description": "Optional: specific collection name to inspect",
                        },
                    },
                },
            ),
            Tool(
                name="get_build_options",
                description=(
                    "Get ALL valid feat options for a character build, organized by feat slot. "
                    "Returns exhaustive lists of class feats, ancestry feats, general feats, "
                    "skill feats, and archetype feats for each slot at each level. "
                    "Use this instead of search when you need complete option lists for building a character."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "class_name": {
                            "type": "string",
                            "description": "Character class (e.g., 'thaumaturge', 'fighter', 'wizard')",
                        },
                        "character_level": {
                            "type": "integer",
                            "description": "Character level (1-20)",
                        },
                        "ancestry_name": {
                            "type": "string",
                            "description": "Character ancestry (e.g., 'goblin', 'elf', 'dwarf')",
                        },
                        "dedications": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Archetype dedications (e.g., ['champion', 'exemplar'])",
                        },
                    },
                    "required": ["class_name", "character_level"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "search_pf2e_rules":
            results = db.search(
                query=arguments["query"],
                source=arguments.get("source"),
                content_type=arguments.get("content_type"),
                level_min=arguments.get("level_min"),
                level_max=arguments.get("level_max"),
                traits=arguments.get("traits"),
                category=arguments.get("category"),
                action_type=arguments.get("action_type"),
                n_results=arguments.get("n_results", 5),
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_pf2e_entry":
            entry = db.get_entry(
                name=arguments["name"],
                source=arguments.get("source"),
                content_type=arguments.get("content_type"),
            )
            if entry:
                return [TextContent(type="text", text=json.dumps(entry, indent=2))]
            return [TextContent(type="text", text=f"No entry found with name: {arguments['name']}")]

        elif name == "list_pf2e_content_types":
            source = arguments.get("source")
            try:
                types = db.list_content_types(source)
                collections = db.list_collections()
                result = {
                    "content_types": types,
                    "collections": collections,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {e}")]

        elif name == "get_build_options":
            try:
                options = get_build_options(
                    class_name=arguments["class_name"],
                    character_level=arguments["character_level"],
                    ancestry_name=arguments.get("ancestry_name", ""),
                    dedications=arguments.get("dedications"),
                )
                result = []
                for so in options.slot_options:
                    slot_data = {
                        "slot_type": so.slot.slot_type,
                        "slot_level": so.slot.level,
                        "source": so.slot.source,
                        "option_count": len(so.options),
                        "options": [
                            {
                                "name": o.name,
                                "level": o.level,
                                "traits": o.traits,
                                "prerequisites": o.prerequisites,
                                "rarity": o.rarity,
                            }
                            for o in so.options
                        ],
                    }
                    result.append(slot_data)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {e}")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
