"""Command-line entry points for stdio, HTTP, setup, and documentation."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

from bambu_mcp.api import create_app
from bambu_mcp.config import Settings
from bambu_mcp.container import build_container
from bambu_mcp.docs import generate_references
from bambu_mcp.mcp_server import create_mcp


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bambu-mcp", description="Safety-gated Bambu MCP")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("stdio", help="run MCP over stdio")
    commands.add_parser("http", help="run MCP and the narrow API over HTTP")
    keygen = commands.add_parser("keygen", help="generate secret material")
    keygen.add_argument("kind", choices=("credential", "api"))
    docs = commands.add_parser("generate-docs", help="regenerate committed API references")
    docs.add_argument("--output", type=Path, default=Path("docs/generated"))
    commands.add_parser("init-db", help="create/migrate the configured database")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "keygen":
        print(
            Fernet.generate_key().decode()
            if args.kind == "credential"
            else secrets.token_urlsafe(32)
        )
        return None
    if args.command == "generate-docs":
        generate_references(args.output)
        return None

    settings = Settings()
    container = build_container(settings)
    if args.command == "init-db":
        container.database.create_schema()
        container.database.engine.dispose()
        return None
    if args.command == "stdio":
        create_mcp(container).run(transport="stdio")
        return None
    if args.command == "http":
        uvicorn.run(
            create_app(container),
            host=settings.bind_host,
            port=settings.bind_port,
            log_level=settings.log_level.lower(),
        )
        return None
    raise SystemExit(2)
