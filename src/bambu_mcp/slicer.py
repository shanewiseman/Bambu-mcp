"""Client contract for the isolated Bambu Studio sidecar."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

import httpx

from bambu_mcp.errors import SlicerError
from bambu_mcp.schemas import SliceSettings

IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class Slicer(Protocol):
    version: str

    async def ready(self) -> bool: ...

    async def slice(
        self,
        *,
        job_id: str,
        artifact_id: str,
        filename: str,
        kind: str,
        settings: SliceSettings,
    ) -> Path: ...


class HttpSlicer:
    def __init__(
        self,
        base_url: str,
        artifact_root: Path,
        *,
        version: str,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.artifact_root = artifact_root.resolve()
        self.version = version
        self.timeout = timeout

    async def ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/readyz")
                payload = response.json()
            return (
                response.is_success
                and isinstance(payload, dict)
                and payload.get("ready") is True
                and payload.get("version") == self.version
            )
        except (httpx.HTTPError, ValueError):
            return False

    async def slice(
        self,
        *,
        job_id: str,
        artifact_id: str,
        filename: str,
        kind: str,
        settings: SliceSettings,
    ) -> Path:
        if not IDENTIFIER.fullmatch(job_id):
            raise SlicerError("job ID is unsafe for sidecar exchange")
        request = {
            "job_id": job_id,
            "artifact_id": artifact_id,
            "filename": filename,
            "kind": kind,
            "settings": settings.model_dump(mode="json"),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/slice", json=request)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SlicerError("Bambu Studio sidecar request failed") from exc
        if payload.get("version") != self.version:
            raise SlicerError("slicer returned an unexpected version")
        output = (self.artifact_root / "work" / job_id / "output.gcode.3mf").resolve()
        if not output.is_relative_to(self.artifact_root) or not output.is_file():
            raise SlicerError("slicer did not produce the expected shared artifact")
        return output


class FakeSlicer:
    """Test slicer that copies a supplied valid golden archive."""

    def __init__(
        self,
        artifact_root: Path,
        golden_output: bytes,
        *,
        version: str = "2.7.1.62",
        dual_nozzle: bool = True,
        available: bool = True,
    ) -> None:
        self.artifact_root = artifact_root
        self.golden_output = golden_output
        self.version = version
        self.dual_nozzle = dual_nozzle
        self.available = available
        self.requests: list[dict[str, Any]] = []

    async def ready(self) -> bool:
        return self.available

    async def slice(
        self,
        *,
        job_id: str,
        artifact_id: str,
        filename: str,
        kind: str,
        settings: SliceSettings,
    ) -> Path:
        if not self.available:
            raise SlicerError("simulated slicer is unavailable")
        if len(settings.nozzle_diameters) == 2 and not self.dual_nozzle:
            raise SlicerError("dual-nozzle slicer smoke test failed")
        self.requests.append(
            {
                "job_id": job_id,
                "artifact_id": artifact_id,
                "filename": filename,
                "kind": kind,
                "settings": settings.model_dump(mode="json"),
            }
        )
        output = self.artifact_root / "work" / job_id / "output.gcode.3mf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.golden_output)
        return output
