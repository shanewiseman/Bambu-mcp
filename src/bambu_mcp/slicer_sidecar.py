"""Minimal, network-isolated Bambu Studio CLI sidecar."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from bambu_mcp.artifacts import ArchivePolicy
from bambu_mcp.schemas import SliceSettings

VERSION = os.getenv("BAMBU_STUDIO_VERSION", "2.7.1.62")
BINARY = Path(os.getenv("BAMBU_STUDIO_BINARY", "/opt/bambu-studio/bambu-studio"))
ARTIFACT_ROOT = Path(os.getenv("BAMBU_ARTIFACT_ROOT", "/artifacts")).resolve()
PROFILE_ROOT = Path(os.getenv("BAMBU_PROFILE_ROOT", "/profiles")).resolve()
# Compose mounts this dedicated location as an ephemeral, non-executable tmpfs.
SLICER_HOME = os.getenv("BAMBU_SLICER_HOME", "/tmp/bambu-slicer")  # noqa: S108  # nosec B108
DUAL_SMOKE_OK = os.getenv("BAMBU_DUAL_NOZZLE_SMOKE_OK", "false").lower() == "true"
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class SliceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=SAFE_ID.pattern)
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str
    kind: Literal["stl", "3mf"]
    settings: SliceSettings


def profile_path(group: str, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9 ._()-]{1,120}", name):
        raise ValueError("profile name contains unsafe characters")
    resolved = (PROFILE_ROOT / group / f"{name}.json").resolve()
    if not resolved.is_relative_to(PROFILE_ROOT) or not resolved.is_file():
        raise ValueError(f"full {group} profile is not mounted: {name}")
    return resolved


def artifact_path(artifact_id: str) -> Path:
    path = (ARTIFACT_ROOT / artifact_id[:2] / artifact_id).resolve()
    if not path.is_relative_to(ARTIFACT_ROOT) or not path.is_file():
        raise ValueError("source artifact is unavailable")
    return path


def build_command(request: SliceRequest, source: Path, output: Path) -> list[str]:
    machine = profile_path("machine", request.settings.printer_profile)
    process = profile_path("process", request.settings.process_profile)
    filaments = [profile_path("filament", name) for name in request.settings.filament_profiles]
    command = [
        str(BINARY),
        "--debug",
        "2",
        "--load-settings",
        f"{machine};{process}",
        "--load-filaments",
        ";".join(str(path) for path in filaments),
        "--curr-bed-type",
        request.settings.bed_type,
        "--arrange",
        "1",
    ]
    if request.settings.orient:
        command.append("--orient")
    command.extend(
        [
            "--slice",
            str(request.settings.plate),
            "--export-3mf",
            str(output),
            str(source),
        ]
    )
    return command


async def binary_version() -> bool:
    if not await asyncio.to_thread(BINARY.is_file):
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            str(BINARY),
            "--help",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return False
    try:
        return await asyncio.wait_for(process.wait(), timeout=30) == 0
    except TimeoutError:
        process.kill()
        await process.wait()
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Bambu MCP Slicer Sidecar",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": VERSION}


@app.get("/readyz")
async def ready() -> dict[str, Any]:
    return {
        "ready": await binary_version(),
        "version": VERSION,
        "dual_nozzle_smoke": DUAL_SMOKE_OK,
    }


@app.post("/slice")
async def slice_model(request: SliceRequest) -> dict[str, Any]:
    if len(request.settings.nozzle_diameters) == 2 and not DUAL_SMOKE_OK:
        raise HTTPException(
            status_code=409,
            detail="dual-nozzle slicing is disabled until its startup smoke test passes",
        )
    try:
        stored = artifact_path(request.artifact_id)
        work_root_path = ARTIFACT_ROOT / "work"
        if work_root_path.is_symlink():
            raise ValueError("unsafe work directory")
        work_root_path.mkdir(parents=True, exist_ok=True, mode=0o2770)
        work_root = work_root_path.resolve()
        if not work_root.is_relative_to(ARTIFACT_ROOT):
            raise ValueError("unsafe work directory")
        work_root.chmod(0o2770)
        work_path = work_root / request.job_id
        if work_path.is_symlink():
            raise ValueError("unsafe work directory")
        work_path.mkdir(mode=0o2770, exist_ok=True)
        work = work_path.resolve()
        if not work.is_relative_to(work_root) or not work.is_dir():
            raise ValueError("unsafe work directory")
        work.chmod(0o2770)
        source = work / f"source.{request.kind}"
        output = work / "output.gcode.3mf"
        for stale in (work / "source.stl", work / "source.3mf", output):
            if stale.is_dir():
                raise ValueError("unexpected directory in slicer workspace")
            stale.unlink(missing_ok=True)
        shutil.copyfile(stored, source)
        source.chmod(0o640)
        command = build_command(request, source, output)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"HOME": SLICER_HOME, "PATH": os.getenv("PATH", "/usr/bin:/bin")},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise HTTPException(status_code=504, detail="Bambu Studio timed out") from exc
    if process.returncode != 0:
        detail = (stderr or stdout).decode(errors="replace")[-1_000:]
        raise HTTPException(status_code=422, detail=f"Bambu Studio failed: {detail}")
    try:
        output.chmod(0o640)
        metadata = ArchivePolicy(10_000, 2 * 1024**3).validate(output, sliced=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid sliced output: {exc}") from exc
    return {"version": VERSION, "output": "output.gcode.3mf", "metadata": metadata}
