"""PF2e Rules MCP Server entry point."""

import asyncio
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server

from .db import PF2eDB
from .tools import register_tools


def create_server() -> tuple[Server, PF2eDB]:
    app = Server("pf2e-rules")

    default_db = os.path.join(os.path.dirname(__file__), "..", "..", "_state", "vector_db", "pf2e_chroma")
    db_path = os.environ.get("PF2E_DB_PATH", os.path.realpath(default_db))
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    model = os.environ.get("PF2E_EMBED_MODEL", "mxbai")
    db = PF2eDB(db_path=db_path, ollama_url=ollama_url, model=model)
    register_tools(app, db)

    return app, db


async def main():
    app, _db = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
