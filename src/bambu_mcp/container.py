"""Dependency composition for HTTP, MCP, CLI, and tests."""

from __future__ import annotations

from dataclasses import dataclass

from bambu_mcp.artifacts import ArchivePolicy, ArtifactStore
from bambu_mcp.config import Settings
from bambu_mcp.database import Database
from bambu_mcp.errors import SafetyError
from bambu_mcp.gateway import GatewayPool, LanGateway, SimulatedGateway
from bambu_mcp.models import Printer
from bambu_mcp.security import CredentialVault
from bambu_mcp.slicer import HttpSlicer, Slicer
from bambu_mcp.workflow import WorkflowService


@dataclass
class Container:
    settings: Settings
    database: Database
    artifacts: ArtifactStore
    slicer: Slicer
    gateways: GatewayPool
    vault: CredentialVault
    workflow: WorkflowService

    async def close(self) -> None:
        await self.gateways.close()
        self.database.engine.dispose()


def build_container(settings: Settings, *, slicer: Slicer | None = None) -> Container:
    settings.prepare_directories()
    key = settings.resolved_credential_key
    if not key:
        raise SafetyError("BAMBU_MCP_CREDENTIAL_KEY_FILE (or BAMBU_MCP_CREDENTIAL_KEY) is required")
    database = Database(settings.database_url)
    database.create_schema()
    database.recover_interrupted_jobs()
    artifacts = ArtifactStore(
        settings.artifact_root,
        max_bytes=settings.artifact_max_bytes,
        archive_policy=ArchivePolicy(
            settings.archive_max_entries,
            settings.archive_max_uncompressed_bytes,
        ),
        import_root=settings.import_root,
        enable_local_imports=settings.enable_local_imports,
    )
    selected_slicer = slicer or HttpSlicer(
        settings.slicer_url,
        settings.artifact_root,
        version=settings.slicer_version,
        timeout=settings.slicer_timeout_seconds,
    )

    def factory(printer: Printer, access_code: str) -> SimulatedGateway | LanGateway:
        if settings.allow_simulated_printers:
            return SimulatedGateway()
        return LanGateway(
            host=printer.host,
            serial=printer.serial,
            access_code=access_code,
            ca_file=settings.bambu_ca_file,
            ack_timeout=settings.mqtt_ack_timeout_seconds,
        )

    gateways = GatewayPool(factory)
    vault = CredentialVault(key)
    workflow = WorkflowService(
        settings=settings,
        database=database,
        artifacts=artifacts,
        slicer=selected_slicer,
        gateways=gateways,
        vault=vault,
    )
    return Container(
        settings=settings,
        database=database,
        artifacts=artifacts,
        slicer=selected_slicer,
        gateways=gateways,
        vault=vault,
        workflow=workflow,
    )
