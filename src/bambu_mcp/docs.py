"""Generate committed MCP and OpenAPI consumer references."""

from __future__ import annotations

import json
import tempfile
from inspect import cleandoc
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from bambu_mcp.api import create_app
from bambu_mcp.config import Settings
from bambu_mcp.container import build_container
from bambu_mcp.mcp_server import create_mcp
from bambu_mcp.slicer import FakeSlicer


def _schema_type(schema: dict[str, Any]) -> str:
    if "type" in schema:
        return str(schema["type"])
    if "anyOf" in schema:
        return " | ".join(str(item.get("type", "object")) for item in schema["anyOf"])
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", maxsplit=1)[-1]
    return "object"


def generate_references(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        settings = Settings(
            database_url=f"sqlite:///{temp / 'docs.db'}",
            artifact_root=temp / "artifacts",
            credential_key=Fernet.generate_key().decode(),
            protocol_matrix_path=Path("docs/protocol-capability-matrix.md"),
            allow_simulated_printers=True,
        )
        slicer = FakeSlicer(temp / "artifacts", b"not-used")
        container = build_container(settings, slicer=slicer)
        try:
            app = create_app(container)
            (output_root / "openapi.json").write_text(
                json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            mcp = create_mcp(container)
            lines = [
                "# MCP tool reference",
                "",
                "Generated from the typed server definitions. Do not edit by hand.",
                "",
            ]
            for tool in sorted(mcp._tool_manager.list_tools(), key=lambda item: item.name):
                lines.extend([f"## `{tool.name}`", "", cleandoc(tool.description or ""), ""])
                properties = tool.parameters.get("properties", {})
                required = set(tool.parameters.get("required", []))
                if properties:
                    lines.extend(["| Parameter | Type | Required |", "| --- | --- | --- |"])
                    for name, schema in properties.items():
                        lines.append(
                            f"| `{name}` | `{_schema_type(schema)}` | "
                            f"{'yes' if name in required else 'no'} |"
                        )
                    lines.append("")
            (output_root / "mcp-tools.md").write_text(
                "\n".join(lines).rstrip() + "\n",
                encoding="utf-8",
            )
        finally:
            container.database.engine.dispose()
