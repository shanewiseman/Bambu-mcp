"""X2D/N6 capability adapter and risk-labelled command catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bambu_mcp.errors import SafetyError, ValidationError
from bambu_mcp.schemas import CommandRisk, MaterialRoute, SliceSettings

X2D_MODELS = {"X2D", "N6"}
EXTERNAL_SPOOL_SENTINEL = 254


@dataclass(frozen=True)
class Operation:
    family: str
    command: str
    risk: CommandRisk
    evidence: str
    minimum_firmware: str | None = None


OPERATIONS: dict[str, Operation] = {
    "get_version": Operation("info", "get_version", CommandRisk.READ_ONLY, "community-observed"),
    "pushall": Operation("pushing", "pushall", CommandRisk.READ_ONLY, "community-observed"),
    "pause": Operation("print", "pause", CommandRisk.ROUTINE, "community-observed"),
    "resume": Operation("print", "resume", CommandRisk.ROUTINE, "community-observed"),
    "speed": Operation("print", "print_speed", CommandRisk.ROUTINE, "community-observed"),
    "lights": Operation("system", "ledctrl", CommandRisk.ROUTINE, "community-observed"),
    "camera_recording": Operation(
        "camera", "ipcam_record_set", CommandRisk.ROUTINE, "community-observed"
    ),
    "timelapse": Operation("camera", "ipcam_timelapse", CommandRisk.ROUTINE, "community-observed"),
    "stop": Operation("print", "stop", CommandRisk.GUARDED, "community-observed"),
    "skip_objects": Operation("print", "skip_objects", CommandRisk.GUARDED, "community-observed"),
    "project_file": Operation("print", "project_file", CommandRisk.GUARDED, "community-observed"),
    "temperature": Operation("print", "gcode_line", CommandRisk.GUARDED, "simulated"),
    "fan": Operation("print", "gcode_line", CommandRisk.ROUTINE, "simulated"),
    "home": Operation("print", "gcode_line", CommandRisk.GUARDED, "simulated"),
    "jog": Operation("print", "gcode_line", CommandRisk.GUARDED, "simulated"),
    "load_filament": Operation(
        "print", "ams_change_filament", CommandRisk.GUARDED, "community-observed"
    ),
    "unload_filament": Operation(
        "print", "unload_filament", CommandRisk.GUARDED, "community-observed"
    ),
    "ams_settings": Operation(
        "print", "ams_user_setting", CommandRisk.GUARDED, "community-observed"
    ),
    "ams_rfid": Operation("print", "ams_get_rfid", CommandRisk.GUARDED, "community-observed"),
    "ams_drying": Operation("print", "ams_drying", CommandRisk.GUARDED, "catalogued"),
    "calibration": Operation("print", "calibration", CommandRisk.GUARDED, "community-observed"),
    "file_delete": Operation("ftps", "delete", CommandRisk.GUARDED, "community-observed"),
    "file_upload": Operation("ftps", "upload", CommandRisk.GUARDED, "community-observed"),
    "chamber": Operation("print", "chamber_control", CommandRisk.GUARDED, "catalogued"),
    "airduct": Operation("print", "airduct_control", CommandRisk.GUARDED, "catalogued"),
    "extruder": Operation("print", "select_extruder", CommandRisk.GUARDED, "catalogued"),
    "print_options": Operation(
        "print", "print_option", CommandRisk.EXPERIMENTAL, "community-observed"
    ),
    "pressure_advance": Operation(
        "print", "extrusion_cali_set", CommandRisk.EXPERIMENTAL, "catalogued"
    ),
    "raw_gcode": Operation("print", "gcode_line", CommandRisk.EXPERIMENTAL, "community-observed"),
    "raw_mqtt": Operation("restricted", "restricted", CommandRisk.EXPERIMENTAL, "catalogued"),
    "firmware_upgrade": Operation("upgrade", "start", CommandRisk.FORBIDDEN, "catalogued"),
    "get_access_code": Operation(
        "system", "get_access_code", CommandRisk.FORBIDDEN, "community-observed"
    ),
}


def firmware_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    numbers = re.findall(r"\d+", version)
    return tuple(int(number) for number in numbers[:4])


class X2DAdapter:
    """Translate stable domain inputs into explicit X2D protocol structures."""

    model_names = X2D_MODELS

    def capabilities(self, firmware: str | None) -> dict[str, Any]:
        return {
            "model_family": "X2D/N6",
            "firmware": firmware,
            "dual_nozzle": True,
            "nozzles": ["left", "right"],
            "ams_mapping_fields": ["ams_mapping", "ams_mapping2"],
            "nozzle_mapping": True,
            "external_spool": True,
            "filament_track_switch": {
                "catalogued": True,
                "writes_enabled": False,
                "evidence": "simulated",
            },
            "chamber_heating": {"catalogued": True, "evidence": "simulated"},
            "airducts": {"catalogued": True, "evidence": "simulated"},
            "lights": ["chamber_light", "work_light"],
            "camera": {"protocol": "RTSPS", "snapshot": True},
            "operations": {
                name: {
                    "risk": operation.risk.value,
                    "evidence": operation.evidence,
                    "available": self.operation_available(operation, firmware),
                }
                for name, operation in OPERATIONS.items()
                if operation.risk is not CommandRisk.FORBIDDEN
            },
        }

    @staticmethod
    def operation_available(operation: Operation, firmware: str | None) -> bool:
        return not operation.minimum_firmware or firmware_tuple(firmware) >= firmware_tuple(
            operation.minimum_firmware
        )

    def material_mapping(self, settings: SliceSettings) -> dict[str, Any]:
        if not settings.material_routes:
            if len(settings.filament_profiles) > 1:
                raise ValidationError("multi-material slices require explicit routes")
            return {
                "ams_mapping": [],
                "ams_mapping2": [],
                "nozzle_mapping": [],
                "use_ams": False,
                "fts_mapping": [],
            }
        by_filament: dict[int, MaterialRoute] = {}
        for route in settings.material_routes:
            if route.filament_index in by_filament:
                raise ValidationError("each filament index may be routed only once")
            by_filament[route.filament_index] = route
        expected = set(range(len(settings.filament_profiles)))
        if set(by_filament) != expected:
            raise ValidationError("every sliced filament must have exactly one material route")

        max_index = max(by_filament)
        left: list[int] = [-1] * (max_index + 1)
        right: list[int] = [-1] * (max_index + 1)
        nozzles: list[int] = [-1] * (max_index + 1)
        fts: list[int] = [-1] * (max_index + 1)
        use_ams = False
        for index, route in by_filament.items():
            source = EXTERNAL_SPOOL_SENTINEL if route.external_spool else route.ams_slot
            assert source is not None
            target = left if route.nozzle == "left" else right
            target[index] = source
            nozzles[index] = 0 if route.nozzle == "left" else 1
            fts[index] = route.fts_channel if route.fts_channel is not None else -1
            use_ams = use_ams or route.ams_slot is not None
        return {
            "ams_mapping": left,
            "ams_mapping2": right,
            "nozzle_mapping": nozzles,
            "use_ams": use_ams,
            "fts_mapping": fts,
        }

    @staticmethod
    def require_write_allowed(
        *,
        model: str,
        hardware_verified: bool,
        allow_unverified_x2d_writes: bool,
        developer_mode: bool,
    ) -> None:
        if not developer_mode:
            raise SafetyError("printer Developer Mode is not recorded as enabled")
        if (
            model.upper() in X2D_MODELS
            and not hardware_verified
            and not allow_unverified_x2d_writes
        ):
            raise SafetyError(
                "unverified X2D mutations require BAMBU_MCP_ALLOW_UNVERIFIED_X2D_WRITES=true"
            )


def operation_named(name: str, *, experimental_enabled: bool) -> Operation:
    try:
        operation = OPERATIONS[name]
    except KeyError as exc:
        raise ValidationError(f"operation is not catalogued: {name}") from exc
    if operation.risk is CommandRisk.FORBIDDEN:
        raise SafetyError(f"operation is never exposed: {name}")
    if operation.risk is CommandRisk.EXPERIMENTAL and not experimental_enabled:
        raise SafetyError("experimental tools are disabled")
    return operation
