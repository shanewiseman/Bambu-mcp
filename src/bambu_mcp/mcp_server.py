"""Typed MCP tools and resources backed by the durable application service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from bambu_mcp.container import Container
from bambu_mcp.errors import SafetyError, ValidationError
from bambu_mcp.schemas import PreparePrintRequest, PrinterRegistration, TransformSpec


def create_mcp(container: Container) -> FastMCP:
    workflow = container.workflow
    artifacts = container.artifacts
    database = container.database
    settings = container.settings
    mcp = FastMCP(
        "Bambu MCP",
        instructions=(
            "LAN-first Bambu printer workflows. Use artifact IDs, inspect plans, and obtain "
            "one-use approval tokens before guarded actions. X2D writes fail closed unless "
            "the operator explicitly enables unverified writes."
        ),
        json_response=True,
        stateless_http=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    def register_printer(request: PrinterRegistration) -> dict[str, Any]:
        """Register an X2D/N6 printer; its access code is encrypted at rest."""
        return workflow.register_printer(request).model_dump(mode="json")

    @mcp.tool()
    def list_printers() -> list[dict[str, Any]]:
        """List registered printers without exposing credentials."""
        return [item.model_dump(mode="json") for item in workflow.list_printers()]

    @mcp.tool()
    async def discover_printer_capabilities(printer_id: str) -> dict[str, Any]:
        """Read firmware and refresh the model/firmware capability snapshot."""
        return (await workflow.discover_capabilities(printer_id)).model_dump(mode="json")

    @mcp.tool()
    async def get_printer_status(printer_id: str) -> dict[str, Any]:
        """Return the merged sparse status report with secrets redacted."""
        return await workflow.printer_status(printer_id)

    @mcp.tool()
    async def get_printer_version(printer_id: str) -> dict[str, Any]:
        """Request module versions from the printer."""
        result = await workflow.run_operation(printer_id=printer_id, operation="get_version")
        return result.model_dump(mode="json")

    @mcp.tool()
    async def get_nozzle_state(printer_id: str) -> dict[str, Any]:
        """Read active tool, nozzle temperatures, diameters, and targets."""
        state = (await workflow.printer_status(printer_id)).get("print", {})
        keys = ("active_tool", "nozzle_diameter", "nozzle_temper", "nozzle_target_temper")
        return {key: state.get(key) for key in keys}

    @mcp.tool()
    async def get_ams_inventory(printer_id: str) -> dict[str, Any]:
        """Read AMS units, trays, and the external-spool virtual tray."""
        state = (await workflow.printer_status(printer_id)).get("print", {})
        return {"ams": state.get("ams", {}), "external_spool": state.get("vt_tray")}

    @mcp.tool()
    async def get_fts_state(printer_id: str) -> dict[str, Any]:
        """Read catalogued Filament Track Switch fields without enabling FTS writes."""
        state = (await workflow.printer_status(printer_id)).get("print", {})
        return {key: value for key, value in state.items() if "fts" in key.lower()}

    @mcp.tool()
    async def get_hms_faults(printer_id: str) -> list[dict[str, Any]]:
        """Read current Health Management System faults."""
        faults = (await workflow.printer_status(printer_id)).get("print", {}).get("hms", [])
        return (
            [item for item in faults if isinstance(item, dict)] if isinstance(faults, list) else []
        )

    @mcp.tool()
    async def list_printer_files(printer_id: str) -> list[str]:
        """List printer storage over implicit FTPS."""
        return await workflow.printer_files(printer_id)

    @mcp.tool()
    async def capture_camera_snapshot(printer_id: str) -> dict[str, Any]:
        """Capture one RTSPS frame and return its immutable artifact metadata."""
        return await workflow.camera_snapshot(printer_id)

    @mcp.tool()
    def import_local_artifact(path: str) -> dict[str, Any]:
        """Import a file only from the operator-mounted /imports allowlist."""
        with database.session() as session:
            artifact = artifacts.import_local(session, Path(path))
            return artifacts.view(artifact).model_dump(mode="json")

    @mcp.tool()
    def get_artifact_metadata(artifact_id: str) -> dict[str, Any]:
        """Return immutable artifact metadata by SHA-256 ID."""
        with database.session() as session:
            return artifacts.view(artifacts.get(session, artifact_id)).model_dump(mode="json")

    @mcp.tool()
    def inspect_model(artifact_id: str) -> dict[str, Any]:
        """Return hardened 3MF or geometric STL inspection results."""
        with database.session() as session:
            artifact = artifacts.get(session, artifact_id)
            return {"artifact_id": artifact.id, "kind": artifact.kind, **artifact.metadata_json}

    @mcp.tool()
    def inspect_3mf(artifact_id: str) -> dict[str, Any]:
        """Revalidate a 3MF archive and report its safe members."""
        with database.session() as session:
            artifact = artifacts.get(session, artifact_id)
            if artifact.kind not in {"3mf", "gcode-3mf"}:
                raise ValidationError("artifact is not a 3MF archive")
            return artifacts.archive_policy.validate(
                artifacts.path_for(artifact.id), sliced=artifact.kind == "gcode-3mf"
            )

    @mcp.tool()
    def transform_model(
        artifact_id: str,
        transform: TransformSpec,
        repair: bool = False,
    ) -> dict[str, Any]:
        """Create a repaired/transformed immutable STL artifact."""
        with database.session() as session:
            output = artifacts.transform_stl(session, artifact_id, transform, repair=repair)
            return artifacts.view(output).model_dump(mode="json")

    @mcp.tool()
    def repair_model(artifact_id: str) -> dict[str, Any]:
        """Create a conservatively repaired STL without changing its placement."""
        with database.session() as session:
            output = artifacts.transform_stl(session, artifact_id, TransformSpec(), repair=True)
            return artifacts.view(output).model_dump(mode="json")

    @mcp.tool()
    def get_artifact_download_url(artifact_id: str) -> dict[str, str]:
        """Return the authenticated HTTP download URL for an artifact."""
        with database.session() as session:
            artifacts.get(session, artifact_id)
        return {
            "artifact_id": artifact_id,
            "url": f"{settings.public_base_url}/api/v1/artifacts/{artifact_id}/content",
        }

    @mcp.tool()
    async def prepare_print_pipeline(request: PreparePrintRequest) -> dict[str, Any]:
        """Inspect, slice, validate, map material, live-preflight, then stop for approval."""
        return (await workflow.prepare_print_pipeline(request)).model_dump(mode="json")

    @mcp.tool()
    async def submit_stl_pipeline(request: PreparePrintRequest) -> dict[str, Any]:
        """Convenience alias that prepares an STL workflow and stops before printer writes."""
        return (await workflow.submit_stl_pipeline(request)).model_dump(mode="json")

    @mcp.tool()
    def approve_print_plan(job_id: str) -> dict[str, Any]:
        """Issue a one-use ten-minute token bound to the immutable print plan digest."""
        return workflow.approve_print_plan(job_id).model_dump(mode="json")

    @mcp.tool()
    def approve_guarded_action(
        job_id: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a one-use token bound to one exact guarded action and parameter set."""
        return workflow.approve_guarded_action(job_id, operation, parameters).model_dump(
            mode="json"
        )

    @mcp.tool()
    async def execute_print_pipeline(job_id: str, approval_token: str) -> dict[str, Any]:
        """Re-preflight, upload, verify, start, require acknowledgement, and monitor."""
        return (await workflow.execute_print_pipeline(job_id, approval_token)).model_dump(
            mode="json"
        )

    @mcp.tool()
    def list_print_queue(printer_id: str | None = None) -> list[dict[str, Any]]:
        """List non-terminal durable jobs in submission order."""
        return [job.model_dump(mode="json") for job in workflow.queue(printer_id)]

    @mcp.tool()
    async def monitor_print_job(job_id: str) -> dict[str, Any]:
        """Merge live printer state into the durable job lifecycle."""
        return (await workflow.monitor_job(job_id)).model_dump(mode="json")

    @mcp.tool()
    async def pause_and_diagnose(job_id: str) -> dict[str, Any]:
        """Pause a running job and return current HMS/print diagnostics."""
        return await workflow.pause_and_diagnose(job_id)

    @mcp.tool()
    async def resume_print_job(job_id: str) -> dict[str, Any]:
        """Resume a durably paused job after acknowledgement."""
        return (await workflow.resume_job(job_id)).model_dump(mode="json")

    @mcp.tool()
    async def cancel_print_job(job_id: str, approval_token: str) -> dict[str, Any]:
        """Safely stop and cancel a job using an exact one-use approval."""
        return (await workflow.cancel_job(job_id, approval_token)).model_dump(mode="json")

    @mcp.tool()
    def archive_completed_job(job_id: str) -> dict[str, Any]:
        """Return a portable completion record with artifact and event evidence."""
        return workflow.completed_job_archive(job_id)

    async def operation(
        printer_id: str,
        name: str,
        parameters: dict[str, Any] | None = None,
        job_id: str | None = None,
        approval_token: str | None = None,
    ) -> dict[str, Any]:
        result = await workflow.run_operation(
            printer_id=printer_id,
            operation=name,
            parameters=parameters,
            job_id=job_id,
            approval_token=approval_token,
        )
        return result.model_dump(mode="json")

    @mcp.tool()
    async def pause_printer(printer_id: str) -> dict[str, Any]:
        """Pause the current print and require a correlated acknowledgement."""
        return await operation(printer_id, "pause")

    @mcp.tool()
    async def resume_printer(printer_id: str) -> dict[str, Any]:
        """Resume the current print and require a correlated acknowledgement."""
        return await operation(printer_id, "resume")

    @mcp.tool()
    async def set_print_speed(printer_id: str, level: Literal[1, 2, 3, 4]) -> dict[str, Any]:
        """Set silent, standard, sport, or ludicrous speed."""
        return await operation(printer_id, "speed", {"param": str(level)})

    @mcp.tool()
    async def set_light(
        printer_id: str,
        node: Literal["chamber_light", "work_light"],
        mode: Literal["on", "off", "flashing"],
    ) -> dict[str, Any]:
        """Control either catalogued X2D light."""
        return await operation(
            printer_id,
            "lights",
            {
                "led_node": node,
                "led_mode": mode,
                "led_on_time": 500,
                "led_off_time": 500,
                "loop_times": 1,
                "interval_time": 1000,
            },
        )

    @mcp.tool()
    async def set_fan(printer_id: str, fan: Literal[0, 1, 2], percent: int) -> dict[str, Any]:
        """Set a fan from 0-100 percent through bounded G-code."""
        if not 0 <= percent <= 100:
            raise ValidationError("fan percent must be between 0 and 100")
        return await operation(
            printer_id, "fan", {"param": f"M106 P{fan} S{round(percent * 2.55)}"}
        )

    @mcp.tool()
    async def set_camera_recording(printer_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable on-printer camera recording."""
        return await operation(
            printer_id, "camera_recording", {"control": "enable" if enabled else "disable"}
        )

    @mcp.tool()
    async def set_timelapse(printer_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable on-printer timelapse capture."""
        return await operation(
            printer_id, "timelapse", {"control": "enable" if enabled else "disable"}
        )

    @mcp.tool()
    async def stop_printer(printer_id: str, job_id: str, approval_token: str) -> dict[str, Any]:
        """Stop the active print with a one-use guarded approval."""
        return await operation(printer_id, "stop", {"param": ""}, job_id, approval_token)

    @mcp.tool()
    async def skip_objects(
        printer_id: str, job_id: str, object_ids: list[int], approval_token: str
    ) -> dict[str, Any]:
        """Skip validated positive object IDs with a one-use approval."""
        if not object_ids or any(item <= 0 for item in object_ids):
            raise ValidationError("object IDs must be positive and non-empty")
        return await operation(
            printer_id,
            "skip_objects",
            {"obj_list": sorted(set(object_ids))},
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def set_temperature(
        printer_id: str,
        job_id: str,
        target: Literal["bed", "left_nozzle", "right_nozzle", "chamber"],
        celsius: int,
        approval_token: str,
    ) -> dict[str, Any]:
        """Set a bounded temperature target with a one-use approval."""
        limits = {
            "bed": (0, 120),
            "left_nozzle": (0, 320),
            "right_nozzle": (0, 320),
            "chamber": (0, 80),
        }
        low, high = limits[target]
        if not low <= celsius <= high:
            raise ValidationError(f"{target} temperature must be between {low} and {high} C")
        commands = {
            "bed": "M140",
            "left_nozzle": "M104 T0",
            "right_nozzle": "M104 T1",
            "chamber": "M141",
        }
        return await operation(
            printer_id,
            "temperature",
            {"param": f"{commands[target]} S{celsius}"},
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def set_chamber(
        printer_id: str, job_id: str, celsius: int, approval_token: str
    ) -> dict[str, Any]:
        """Request an X2D chamber target; catalogued but unverified writes fail closed."""
        if not 0 <= celsius <= 80:
            raise ValidationError("chamber target must be between 0 and 80 C")
        return await operation(printer_id, "chamber", {"target": celsius}, job_id, approval_token)

    @mcp.tool()
    async def set_airduct(
        printer_id: str, job_id: str, channel: int, percent: int, approval_token: str
    ) -> dict[str, Any]:
        """Set a bounded X2D airduct channel with a one-use approval."""
        if channel not in {0, 1, 2} or not 0 <= percent <= 100:
            raise ValidationError("airduct channel/percent is outside policy")
        return await operation(
            printer_id, "airduct", {"channel": channel, "percent": percent}, job_id, approval_token
        )

    @mcp.tool()
    async def select_extruder(
        printer_id: str, job_id: str, extruder: Literal["left", "right"], approval_token: str
    ) -> dict[str, Any]:
        """Select the X2D active extruder with a guarded approval."""
        return await operation(
            printer_id, "extruder", {"extruder": extruder}, job_id, approval_token
        )

    @mcp.tool()
    async def home_axes(
        printer_id: str, job_id: str, axes: Literal["XY", "Z", "XYZ"], approval_token: str
    ) -> dict[str, Any]:
        """Home an allowlisted axis set with a guarded approval."""
        return await operation(printer_id, "home", {"param": f"G28 {axes}"}, job_id, approval_token)

    @mcp.tool()
    async def jog_axis(
        printer_id: str,
        job_id: str,
        axis: Literal["X", "Y", "Z"],
        millimeters: float,
        feedrate: int,
        approval_token: str,
    ) -> dict[str, Any]:
        """Jog one axis within bounded distance/feedrate limits."""
        if abs(millimeters) > 50 or not 60 <= feedrate <= 6000:
            raise ValidationError("jog distance or feedrate is outside policy")
        return await operation(
            printer_id,
            "jog",
            {"param": f"G91\nG0 {axis}{millimeters:.3f} F{feedrate}\nG90"},
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def load_filament(
        printer_id: str, job_id: str, slot: int, target_temperature: int, approval_token: str
    ) -> dict[str, Any]:
        """Load an AMS slot using bounded temperature and slot values."""
        if not 0 <= slot <= 31 or not 150 <= target_temperature <= 320:
            raise ValidationError("filament load values are outside policy")
        return await operation(
            printer_id,
            "load_filament",
            {"target": slot, "curr_temp": 0, "tar_temp": target_temperature},
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def unload_filament(printer_id: str, job_id: str, approval_token: str) -> dict[str, Any]:
        """Unload filament using a one-use approval."""
        return await operation(printer_id, "unload_filament", {}, job_id, approval_token)

    @mcp.tool()
    async def configure_ams(
        printer_id: str,
        job_id: str,
        ams_id: int,
        startup_read: bool,
        insertion_read: bool,
        approval_token: str,
    ) -> dict[str, Any]:
        """Configure AMS RFID read behavior."""
        if not 0 <= ams_id <= 7:
            raise ValidationError("AMS ID is outside policy")
        return await operation(
            printer_id,
            "ams_settings",
            {
                "ams_id": ams_id,
                "startup_read_option": startup_read,
                "tray_read_option": insertion_read,
            },
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def read_ams_rfid(
        printer_id: str, job_id: str, ams_id: int, slot_id: int, approval_token: str
    ) -> dict[str, Any]:
        """Request an AMS RFID refresh with a guarded approval."""
        if not 0 <= ams_id <= 7 or not 0 <= slot_id <= 3:
            raise ValidationError("AMS/slot ID is outside policy")
        return await operation(
            printer_id, "ams_rfid", {"ams_id": ams_id, "slot_id": slot_id}, job_id, approval_token
        )

    @mcp.tool()
    async def dry_ams_filament(
        printer_id: str, job_id: str, ams_id: int, celsius: int, minutes: int, approval_token: str
    ) -> dict[str, Any]:
        """Request catalogued AMS drying; unverified X2D writes remain fail-closed."""
        if not 0 <= ams_id <= 7 or not 0 <= celsius <= 80 or not 1 <= minutes <= 1440:
            raise ValidationError("AMS drying values are outside policy")
        return await operation(
            printer_id,
            "ams_drying",
            {"ams_id": ams_id, "temperature": celsius, "minutes": minutes},
            job_id,
            approval_token,
        )

    @mcp.tool()
    async def run_calibration(
        printer_id: str, job_id: str, option_mask: int, approval_token: str
    ) -> dict[str, Any]:
        """Run only documented calibration option bits 0-3."""
        if not 0 <= option_mask <= 15:
            raise ValidationError("calibration option mask must use only bits 0-3")
        return await operation(
            printer_id, "calibration", {"option": option_mask}, job_id, approval_token
        )

    @mcp.tool()
    async def upload_printer_file(
        printer_id: str, artifact_id: str, filename: str, job_id: str, approval_token: str
    ) -> dict[str, Any]:
        """Upload an immutable artifact over FTPS with a one-use approval."""
        await workflow.upload_artifact_to_printer(
            printer_id, artifact_id, filename, job_id, approval_token
        )
        return {"uploaded": True, "filename": filename, "artifact_id": artifact_id}

    @mcp.tool()
    async def delete_printer_file(
        printer_id: str, filename: str, job_id: str, approval_token: str
    ) -> dict[str, Any]:
        """Delete one printer basename over FTPS with a one-use approval."""
        await workflow.delete_printer_file(printer_id, filename, job_id, approval_token)
        return {"deleted": True, "filename": filename}

    @mcp.tool()
    async def set_pressure_advance(
        printer_id: str, job_id: str, profile: dict[str, Any], approval_token: str
    ) -> dict[str, Any]:
        """Experimental pressure-advance profile write; disabled by default."""
        return await operation(printer_id, "pressure_advance", profile, job_id, approval_token)

    @mcp.tool()
    async def set_detection_options(
        printer_id: str, job_id: str, options: dict[str, bool], approval_token: str
    ) -> dict[str, Any]:
        """Experimental detection/print options; disabled by default."""
        allowed = {
            "auto_recovery",
            "air_print_detect",
            "filament_tangle_detect",
            "nozzle_blob_detect",
            "sound_enable",
        }
        if not options or not set(options) <= allowed:
            raise ValidationError("one or more print options are not allowlisted")
        return await operation(printer_id, "print_options", options, job_id, approval_token)

    @mcp.tool()
    async def send_raw_gcode(
        printer_id: str, job_id: str, gcode: str, approval_token: str
    ) -> dict[str, Any]:
        """Experimental raw G-code; disabled by default and length/control bounded."""
        if len(gcode) > 4096 or "\x00" in gcode:
            raise ValidationError("raw G-code exceeds policy")
        return await operation(printer_id, "raw_gcode", {"param": gcode}, job_id, approval_token)

    @mcp.tool()
    async def send_raw_mqtt(
        printer_id: str,
        job_id: str,
        family: str,
        command: str,
        parameters: dict[str, Any],
        approval_token: str,
    ) -> dict[str, Any]:
        """Send an experimental request-topic command.

        Arbitrary topics and forbidden families remain blocked.
        """
        result = await workflow.run_raw_mqtt(
            printer_id=printer_id,
            family=family,
            command=command,
            parameters=parameters,
            job_id=job_id,
            approval_token=approval_token,
        )
        return result.model_dump(mode="json")

    @mcp.resource("bambu://printers/{printer_id}/status")
    async def printer_status_resource(printer_id: str) -> str:
        """Current redacted printer status."""
        return json.dumps(await workflow.printer_status(printer_id), sort_keys=True)

    @mcp.resource("bambu://printers/{printer_id}/capabilities")
    def printer_capabilities_resource(printer_id: str) -> str:
        """Durable model/firmware capability snapshot."""
        return workflow.get_printer(printer_id).model_dump_json()

    @mcp.resource("bambu://printers/{printer_id}/ams")
    async def printer_ams_resource(printer_id: str) -> str:
        """Current AMS and external-spool inventory."""
        state = (await workflow.printer_status(printer_id)).get("print", {})
        return json.dumps(
            {"ams": state.get("ams"), "vt_tray": state.get("vt_tray")}, sort_keys=True
        )

    @mcp.resource("bambu://printers/{printer_id}/hms")
    async def printer_hms_resource(printer_id: str) -> str:
        """Current HMS faults."""
        state = (await workflow.printer_status(printer_id)).get("print", {})
        return json.dumps(state.get("hms", []), sort_keys=True)

    @mcp.resource("bambu://printers/{printer_id}/files")
    async def printer_files_resource(printer_id: str) -> str:
        """Current printer storage listing."""
        return json.dumps(await workflow.printer_files(printer_id))

    @mcp.resource("bambu://jobs/{job_id}")
    def job_resource(job_id: str) -> str:
        """Durable job state and immutable plan."""
        return workflow.get_job(job_id).model_dump_json()

    @mcp.resource("bambu://jobs/{job_id}/events")
    def job_events_resource(job_id: str) -> str:
        """Ordered durable state-transition evidence."""
        return json.dumps(workflow.job_events(job_id), sort_keys=True)

    @mcp.resource("bambu://artifacts/{artifact_id}")
    def artifact_resource(artifact_id: str) -> str:
        """Immutable artifact metadata."""
        with database.session() as session:
            return artifacts.view(artifacts.get(session, artifact_id)).model_dump_json()

    @mcp.resource("bambu://protocol/capability-matrix")
    def protocol_matrix_resource() -> str:
        """Published protocol provenance and evidence matrix."""
        path = settings.protocol_matrix_path.resolve()
        if not path.is_file():
            raise SafetyError("protocol capability matrix is unavailable")
        return path.read_text(encoding="utf-8")

    return mcp
