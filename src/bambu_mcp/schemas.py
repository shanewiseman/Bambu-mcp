"""Typed public schemas shared by MCP, HTTP, protocol, and workflow layers."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, field_validator, model_validator

from bambu_mcp.models import JobState


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PrinterRegistration(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    serial: str = Field(min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    host: IPvAnyAddress | str
    access_code: str = Field(min_length=8, max_length=128)
    model: str = Field(default="X2D", min_length=2, max_length=64)
    developer_mode: bool = False

    @field_validator("host")
    @classmethod
    def reject_host_metacharacters(cls, value: IPvAnyAddress | str) -> str:
        host = str(value)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if any(char in host for char in "/\\:@"):
                raise ValueError("host must be an IP address or bare DNS name") from None
        return host


class PrinterView(StrictModel):
    id: str
    name: str
    serial: str
    host: str
    model: str
    firmware: str | None
    developer_mode: bool
    hardware_verified: bool
    capabilities: dict[str, Any] = Field(default_factory=dict)


class ArtifactView(StrictModel):
    id: str = Field(min_length=64, max_length=64)
    filename: str
    media_type: str
    size: int
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TransformSpec(StrictModel):
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    translate_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @field_validator("scale")
    @classmethod
    def positive_scale(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(component <= 0 or component > 100 for component in value):
            raise ValueError("scale components must be in (0, 100]")
        return value


class MaterialRoute(StrictModel):
    filament_index: int = Field(ge=0, le=31)
    nozzle: Literal["left", "right"]
    ams_slot: int | None = Field(default=None, ge=0, le=31)
    external_spool: bool = False
    fts_channel: int | None = Field(default=None, ge=0, le=7)

    @model_validator(mode="after")
    def exclusive_source(self) -> MaterialRoute:
        if self.external_spool == (self.ams_slot is not None):
            raise ValueError("choose exactly one of ams_slot or external_spool")
        return self


class SliceSettings(StrictModel):
    printer_profile: str = Field(default="X2D", min_length=1, max_length=120)
    bed_type: str = Field(default="auto", min_length=1, max_length=120)
    process_profile: str = Field(default="0.20mm Standard", min_length=1, max_length=120)
    plate: int = Field(default=1, ge=1, le=64)
    nozzle_diameters: tuple[float, ...] = (0.4,)
    filament_profiles: tuple[str, ...] = ("Generic PLA",)
    supports: bool = False
    orient: bool = True
    copies: int = Field(default=1, ge=1, le=100)
    material_routes: tuple[MaterialRoute, ...] = ()

    @field_validator("nozzle_diameters")
    @classmethod
    def supported_nozzles(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not 1 <= len(value) <= 2 or any(size not in {0.2, 0.4, 0.6, 0.8} for size in value):
            raise ValueError("one or two supported nozzle diameters are required")
        return value


class PrintOptions(StrictModel):
    timelapse: bool = False
    bed_levelling: bool = True
    flow_calibration: bool = True
    vibration_calibration: bool = True
    layer_inspection: bool = True


class PreparePrintRequest(StrictModel):
    printer_id: str
    artifact_id: str = Field(min_length=64, max_length=64)
    slice: SliceSettings = Field(default_factory=SliceSettings)
    print_options: PrintOptions = Field(default_factory=PrintOptions)
    transform: TransformSpec | None = None
    repair: bool = False


class JobView(StrictModel):
    id: str
    state: JobState
    printer_id: str
    source_artifact_id: str
    output_artifact_id: str | None
    plan_digest: str | None
    plan: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalView(StrictModel):
    job_id: str
    approval_token: str
    plan_digest: str
    expires_at: datetime


class CommandRisk(StrEnum):
    READ_ONLY = "read-only"
    ROUTINE = "routine"
    GUARDED = "guarded"
    EXPERIMENTAL = "experimental"
    FORBIDDEN = "forbidden"


class PrinterCommand(StrictModel):
    family: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    command: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: CommandRisk
    approval_token: str | None = None


class CommandResult(StrictModel):
    sequence_id: str
    command: str
    result: Literal["success", "failed", "timeout", "rejected"]
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthView(StrictModel):
    status: Literal["ok", "degraded", "not-ready"]
    database: bool
    artifact_store: bool
    slicer: bool | None = None
    slicer_version: str | None = None
