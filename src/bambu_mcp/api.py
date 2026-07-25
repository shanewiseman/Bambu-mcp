"""Narrow authenticated HTTP API and Streamable HTTP MCP composition."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from bambu_mcp.container import Container
from bambu_mcp.errors import (
    BambuMCPError,
    ConflictError,
    NotFoundError,
    SafetyError,
    ValidationError,
)
from bambu_mcp.mcp_server import create_mcp
from bambu_mcp.security import compare_api_key


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    operation: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


def create_app(container: Container) -> FastAPI:
    mcp = create_mcp(container)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        async with mcp.session_manager.run():
            yield
        await container.close()

    app = FastAPI(
        title="Bambu MCP",
        summary="Safety-gated LAN workflows for Bambu Lab printers",
        description=(
            "A narrow artifact and approval API. Printer functionality is exposed through "
            "Model Context Protocol at /mcp, not as general REST endpoints."
        ),
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        if request.url.path in {"/healthz", "/readyz"}:
            return await call_next(request)
        expected = container.settings.resolved_api_key
        authorization = request.headers.get("authorization", "")
        bearer = (
            authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None
        )
        supplied = request.headers.get("x-api-key") or bearer
        if not compare_api_key(expected, supplied):
            return JSONResponse(status_code=401, content={"detail": "invalid API credential"})
        return await call_next(request)

    @app.exception_handler(BambuMCPError)
    async def domain_error(request: Request, exc: BambuMCPError) -> JSONResponse:
        del request
        status = 400
        if isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, ConflictError):
            status = 409
        elif isinstance(exc, SafetyError):
            status = 403
        elif isinstance(exc, ValidationError):
            status = 422
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, Any]:
        database_ok = False
        try:
            with container.database.engine.connect() as connection:
                database_ok = connection.scalar(text("SELECT 1")) == 1
        except SQLAlchemyError:
            database_ok = False
        artifact_ok = container.artifacts.root.is_dir() and os.access(
            container.artifacts.root, os.W_OK
        )
        return {
            "status": "ok" if database_ok and artifact_ok else "degraded",
            "database": database_ok,
            "artifact_store": artifact_ok,
        }

    @app.get("/readyz", tags=["operations"])
    async def ready() -> JSONResponse:
        health_state = health()
        slicer_ok = await container.slicer.ready()
        ready_state = health_state["status"] == "ok" and slicer_ok
        return JSONResponse(
            status_code=200 if ready_state else 503,
            content={
                "status": "ok" if ready_state else "not-ready",
                "database": health_state["database"],
                "artifact_store": health_state["artifact_store"],
                "slicer": slicer_ok,
                "slicer_version": container.slicer.version,
            },
        )

    @app.post("/api/v1/artifacts", status_code=201, tags=["artifacts"])
    def upload_artifact(
        file: Annotated[UploadFile, File()],
        content_length: Annotated[int | None, Header(alias="Content-Length")] = None,
    ) -> dict[str, Any]:
        if content_length and content_length > container.settings.artifact_max_bytes * 2:
            raise HTTPException(status_code=413, detail="request exceeds upload policy")
        filename = file.filename or ""
        with container.database.session() as session:
            artifact = container.artifacts.ingest_stream(session, filename, file.file)
            return container.artifacts.view(artifact).model_dump(mode="json")

    @app.get("/api/v1/artifacts/{artifact_id}", tags=["artifacts"])
    def artifact_metadata(artifact_id: str) -> dict[str, Any]:
        with container.database.session() as session:
            artifact = container.artifacts.get(session, artifact_id)
            return container.artifacts.view(artifact).model_dump(mode="json")

    @app.get("/api/v1/artifacts/{artifact_id}/content", tags=["artifacts"])
    def artifact_content(artifact_id: str) -> FileResponse:
        with container.database.session() as session:
            artifact = container.artifacts.get(session, artifact_id)
            path = container.artifacts.path_for(artifact.id)
            return FileResponse(path, media_type=artifact.media_type, filename=artifact.filename)

    @app.post("/api/v1/approvals", status_code=201, tags=["approvals"])
    def submit_approval(request: ApprovalRequest) -> dict[str, Any]:
        approval = (
            container.workflow.approve_guarded_action(
                request.job_id,
                request.operation,
                request.parameters,
            )
            if request.operation
            else container.workflow.approve_print_plan(request.job_id)
        )
        return approval.model_dump(mode="json")

    app.mount("/mcp", mcp_app)
    return app
