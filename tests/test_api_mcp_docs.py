from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import make_3mf, make_stl
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from test_workflow_pipeline import ingest

from bambu_mcp.api import create_app
from bambu_mcp.cli import main
from bambu_mcp.container import Container
from bambu_mcp.docs import generate_references
from bambu_mcp.mcp_server import create_mcp
from bambu_mcp.schemas import PreparePrintRequest
from bambu_mcp.slicer import FakeSlicer

REPO_ROOT = Path.cwd().resolve()


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-api-key"}


def test_http_auth_health_readiness_upload_download_and_errors(
    container: Container,
) -> None:
    app = create_app(container)
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["slicer"] is True
        assert client.get("/api/v1/artifacts/" + "0" * 64).status_code == 401
        assert (
            client.get(
                "/api/v1/artifacts/" + "0" * 64,
                headers={"X-API-Key": "wrong"},
            ).status_code
            == 401
        )
        for scheme in ("bearer", "bEaReR"):
            response = client.get(
                "/api/v1/artifacts/" + "0" * 64,
                headers={"Authorization": f"{scheme} test-api-key"},
            )
            assert response.status_code == 404
        for malformed in ("bearer", "Basic test-api-key", "bearer  test-api-key"):
            response = client.get(
                "/api/v1/artifacts/" + "0" * 64,
                headers={"Authorization": malformed},
            )
            assert response.status_code == 401
        uploaded = client.post(
            "/api/v1/artifacts",
            headers=auth(),
            files={"file": ("box.stl", make_stl(), "application/sla")},
        )
        assert uploaded.status_code == 201, uploaded.text
        artifact = uploaded.json()
        assert len(artifact["id"]) == 64
        metadata = client.get(f"/api/v1/artifacts/{artifact['id']}", headers=auth())
        assert metadata.json()["metadata"]["watertight"] is True
        content = client.get(f"/api/v1/artifacts/{artifact['id']}/content", headers=auth())
        assert content.status_code == 200
        assert content.content == make_stl()
        assert "box.stl" in content.headers["content-disposition"]
        missing = client.get("/api/v1/artifacts/" + "0" * 64, headers=auth())
        assert missing.status_code == 404
        invalid = client.post(
            "/api/v1/artifacts",
            headers=auth(),
            files={"file": ("bad.obj", b"bad", "application/octet-stream")},
        )
        assert invalid.status_code == 422


def test_http_readiness_failure_and_content_length_guard(container: Container) -> None:
    assert isinstance(container.slicer, FakeSlicer)
    container.slicer.available = False
    with TestClient(create_app(container)) as client:
        assert client.get("/readyz").status_code == 503
        response = client.post(
            "/api/v1/artifacts",
            headers={**auth(), "Content-Length": str(container.settings.artifact_max_bytes * 3)},
            files={"file": ("box.stl", make_stl(), "application/sla")},
        )
        assert response.status_code == 413


@pytest.mark.asyncio
async def test_http_approval_endpoint(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    artifact_id = ingest(container, "ready.gcode.3mf", make_3mf(sliced=True))
    prepared = await container.workflow.prepare_print_pipeline(
        PreparePrintRequest(printer_id=registered_printer["id"], artifact_id=artifact_id)
    )
    with TestClient(create_app(container)) as client:
        approval = client.post(
            "/api/v1/approvals",
            headers=auth(),
            json={"job_id": prepared.id},
        )
        assert approval.status_code == 201
        assert approval.json()["plan_digest"] == prepared.plan_digest
        bad = client.post(
            "/api/v1/approvals",
            headers=auth(),
            json={"job_id": prepared.id, "operation": "pause", "extra": 1},
        )
        assert bad.status_code == 422


def test_mcp_catalog_and_direct_tool_resource_calls(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    mcp = create_mcp(container)
    tools = mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert len(tools) == 56
    assert {
        "register_printer",
        "prepare_print_pipeline",
        "execute_print_pipeline",
        "send_raw_mqtt",
        "capture_camera_snapshot",
    } <= names
    assert "firmware_upgrade" not in names
    assert len(mcp._resource_manager.list_templates()) == 8

    async def calls() -> None:
        result = await mcp._tool_manager.call_tool("list_printers", {}, convert_result=False)
        assert result[0]["id"] == registered_printer["id"]
        resource = await mcp._resource_manager.get_resource(
            f"bambu://printers/{registered_printer['id']}/capabilities"
        )
        assert resource is not None
        content = await resource.read()
        assert "dual_nozzle" in content
        matrix = await mcp._resource_manager.get_resource("bambu://protocol/capability-matrix")
        assert matrix is not None
        assert "Evidence levels" in await matrix.read()

    asyncio.run(calls())


def test_mcp_streamable_http_round_trip(container: Container) -> None:
    headers = {
        **auth(),
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0"},
        },
    }
    with TestClient(create_app(container), base_url="http://127.0.0.1:8000") as client:
        initialized = client.post("/mcp", headers=headers, json=initialize)
        assert initialized.status_code == 200, initialized.text
        payload = initialized.json()
        assert payload["result"]["serverInfo"]["name"] == "Bambu MCP"
        protocol_version = payload["result"]["protocolVersion"]
        tools = client.post(
            "/mcp",
            headers={**headers, "MCP-Protocol-Version": protocol_version},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200, tools.text
        assert len(tools.json()["result"]["tools"]) == 56


def test_generated_references(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    generate_references(output)
    openapi = json.loads((output / "openapi.json").read_text(encoding="utf-8"))
    assert set(openapi["paths"]) == {
        "/healthz",
        "/readyz",
        "/api/v1/artifacts",
        "/api/v1/artifacts/{artifact_id}",
        "/api/v1/artifacts/{artifact_id}/content",
        "/api/v1/approvals",
    }
    tools = (output / "mcp-tools.md").read_text(encoding="utf-8")
    assert tools.count("\n## `") == 56
    assert "`execute_print_pipeline`" in tools


def test_cli_keygen_and_generate_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["bambu-mcp", "keygen", "credential"])
    assert main() is None
    assert len(capsys.readouterr().out.strip()) == 44
    monkeypatch.setattr("sys.argv", ["bambu-mcp", "keygen", "api"])
    assert main() is None
    assert len(capsys.readouterr().out.strip()) > 32
    output = tmp_path / "docs"
    monkeypatch.setattr("sys.argv", ["bambu-mcp", "generate-docs", "--output", str(output)])
    assert main() is None
    assert (output / "openapi.json").is_file()


@pytest.mark.asyncio
async def test_mcp_stdio_round_trip(tmp_path: Path) -> None:
    secret = tmp_path / "credential"
    from cryptography.fernet import Fernet

    secret.write_text(Fernet.generate_key().decode(), encoding="utf-8")
    environment = {
        **os.environ,
        "BAMBU_MCP_CREDENTIAL_KEY_FILE": str(secret),
        "BAMBU_MCP_DATABASE_URL": f"sqlite:///{tmp_path / 'stdio.db'}",
        "BAMBU_MCP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
        "BAMBU_MCP_PROTOCOL_MATRIX_PATH": str(REPO_ROOT / "docs/protocol-capability-matrix.md"),
        "BAMBU_MCP_ALLOW_SIMULATED_PRINTERS": "true",
    }
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bambu_mcp", "stdio"],
        env=environment,
    )
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "Bambu MCP"
        tools = await session.list_tools()
        assert len(tools.tools) == 56
        resources = await session.list_resource_templates()
        assert len(resources.resourceTemplates) == 8
