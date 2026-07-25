from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import make_3mf, make_stl
from helpers import ingest
from mcp.server.fastmcp.exceptions import ToolError

from bambu_mcp.container import Container
from bambu_mcp.mcp_server import create_mcp


@pytest.mark.asyncio
async def test_mcp_read_artifact_routine_and_pipeline_tools(
    container: Container, registered_printer: dict[str, Any], tmp_path: Path
) -> None:
    mcp = create_mcp(container)

    async def call(name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await mcp._tool_manager.call_tool(name, arguments or {}, convert_result=False)

    printer_id = registered_printer["id"]
    assert len(await call("list_printers")) == 1
    assert (await call("get_printer_status", {"printer_id": printer_id}))["print"]
    assert (await call("get_nozzle_state", {"printer_id": printer_id}))["active_tool"] is None
    assert "ams" in await call("get_ams_inventory", {"printer_id": printer_id})
    assert await call("get_fts_state", {"printer_id": printer_id}) == {}
    assert await call("get_hms_faults", {"printer_id": printer_id}) == []
    assert await call("list_printer_files", {"printer_id": printer_id}) == []
    assert (await call("get_printer_version", {"printer_id": printer_id}))["result"] == "success"
    assert (await call("discover_printer_capabilities", {"printer_id": printer_id}))[
        "capabilities"
    ]["dual_nozzle"]

    stl_id = ingest(container, "box.stl", make_stl())
    metadata = await call("get_artifact_metadata", {"artifact_id": stl_id})
    assert metadata["id"] == stl_id
    assert (await call("inspect_model", {"artifact_id": stl_id}))["watertight"]
    transformed = await call(
        "transform_model",
        {
            "artifact_id": stl_id,
            "transform": {
                "scale": [1, 1, 1],
                "translate_mm": [1, 0, 0],
                "rotate_degrees": [0, 0, 0],
            },
        },
    )
    assert transformed["id"] != stl_id
    assert (await call("repair_model", {"artifact_id": stl_id}))["kind"] == "stl"
    assert stl_id in (await call("get_artifact_download_url", {"artifact_id": stl_id}))["url"]
    with pytest.raises(ToolError, match="not a 3MF"):
        await call("inspect_3mf", {"artifact_id": stl_id})

    model_id = ingest(container, "ready.gcode.3mf", make_3mf(sliced=True))
    assert (await call("inspect_3mf", {"artifact_id": model_id}))["sliced"]
    prepared = await call(
        "submit_stl_pipeline",
        {
            "request": {
                "printer_id": printer_id,
                "artifact_id": model_id,
            }
        },
    )
    assert prepared["state"] == "AWAITING_APPROVAL"
    job_id = prepared["id"]
    assert (await call("list_print_queue"))[0]["id"] == job_id
    approval = await call("approve_print_plan", {"job_id": job_id})
    running = await call(
        "execute_print_pipeline",
        {"job_id": job_id, "approval_token": approval["approval_token"]},
    )
    assert running["state"] == "RUNNING"
    assert (await call("monitor_print_job", {"job_id": job_id}))["state"] == "RUNNING"

    for name, arguments in (
        ("pause_printer", {}),
        ("resume_printer", {}),
        ("set_print_speed", {"level": 2}),
        ("set_light", {"node": "chamber_light", "mode": "on"}),
        ("set_fan", {"fan": 0, "percent": 50}),
        ("set_camera_recording", {"enabled": True}),
        ("set_timelapse", {"enabled": False}),
    ):
        result = await call(name, {"printer_id": printer_id, **arguments})
        assert result["result"] == "success"

    imported_root = tmp_path / "imports"
    imported_root.mkdir(exist_ok=True)
    imported = imported_root / "import.stl"
    imported.write_bytes(make_stl())
    container.artifacts.import_root = imported_root
    container.artifacts.enable_local_imports = True
    assert (await call("import_local_artifact", {"path": str(imported)}))["kind"] == "stl"

    async def approve(operation: str, parameters: dict[str, Any]) -> str:
        result = await call(
            "approve_guarded_action",
            {"job_id": job_id, "operation": operation, "parameters": parameters},
        )
        return result["approval_token"]

    guarded: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
        ("stop_printer", "stop", {"param": ""}, {}),
        ("skip_objects", "skip_objects", {"obj_list": [1, 2]}, {"object_ids": [2, 1]}),
        ("set_temperature", "temperature", {"param": "M140 S50"}, {"target": "bed", "celsius": 50}),
        ("set_chamber", "chamber", {"target": 50}, {"celsius": 50}),
        ("set_airduct", "airduct", {"channel": 1, "percent": 20}, {"channel": 1, "percent": 20}),
        ("select_extruder", "extruder", {"extruder": "left"}, {"extruder": "left"}),
        ("home_axes", "home", {"param": "G28 XYZ"}, {"axes": "XYZ"}),
        (
            "jog_axis",
            "jog",
            {"param": "G91\nG0 X1.000 F600\nG90"},
            {"axis": "X", "millimeters": 1.0, "feedrate": 600},
        ),
        (
            "load_filament",
            "load_filament",
            {"target": 0, "curr_temp": 0, "tar_temp": 220},
            {"slot": 0, "target_temperature": 220},
        ),
        ("unload_filament", "unload_filament", {}, {}),
        (
            "configure_ams",
            "ams_settings",
            {"ams_id": 0, "startup_read_option": True, "tray_read_option": True},
            {"ams_id": 0, "startup_read": True, "insertion_read": True},
        ),
        ("read_ams_rfid", "ams_rfid", {"ams_id": 0, "slot_id": 0}, {"ams_id": 0, "slot_id": 0}),
        (
            "dry_ams_filament",
            "ams_drying",
            {"ams_id": 0, "temperature": 50, "minutes": 60},
            {"ams_id": 0, "celsius": 50, "minutes": 60},
        ),
        ("run_calibration", "calibration", {"option": 3}, {"option_mask": 3}),
    ]
    for tool, operation, parameters, arguments in guarded:
        token = await approve(operation, parameters)
        result = await call(
            tool,
            {
                "printer_id": printer_id,
                "job_id": job_id,
                "approval_token": token,
                **arguments,
            },
        )
        assert result["result"] == "success"

    extra_id = ingest(container, "extra.gcode.3mf", make_3mf(sliced=True))
    upload_parameters = {"artifact_id": extra_id, "filename": "extra.gcode.3mf"}
    token = await approve("file_upload", upload_parameters)
    assert (
        await call(
            "upload_printer_file",
            {
                "printer_id": printer_id,
                "artifact_id": extra_id,
                "filename": "extra.gcode.3mf",
                "job_id": job_id,
                "approval_token": token,
            },
        )
    )["uploaded"]
    token = await approve("file_delete", {"filename": "extra.gcode.3mf"})
    assert (
        await call(
            "delete_printer_file",
            {
                "printer_id": printer_id,
                "filename": "extra.gcode.3mf",
                "job_id": job_id,
                "approval_token": token,
            },
        )
    )["deleted"]

    container.settings.enable_experimental_tools = True
    for tool, operation, parameters, arguments in (
        ("set_pressure_advance", "pressure_advance", {"k": 0.02}, {"profile": {"k": 0.02}}),
        (
            "set_detection_options",
            "print_options",
            {"auto_recovery": True},
            {"options": {"auto_recovery": True}},
        ),
        ("send_raw_gcode", "raw_gcode", {"param": "M400"}, {"gcode": "M400"}),
    ):
        token = await approve(operation, parameters)
        assert (
            await call(
                tool,
                {
                    "printer_id": printer_id,
                    "job_id": job_id,
                    "approval_token": token,
                    **arguments,
                },
            )
        )["result"] == "success"
    raw_action = {"family": "print", "command": "custom", "parameters": {"x": 1}}
    token = await approve("raw_mqtt", raw_action)
    assert (
        await call(
            "send_raw_mqtt",
            {
                "printer_id": printer_id,
                "job_id": job_id,
                "family": "print",
                "command": "custom",
                "parameters": {"x": 1},
                "approval_token": token,
            },
        )
    )["result"] == "success"

    diagnosed = await call("pause_and_diagnose", {"job_id": job_id})
    assert diagnosed["state"] == "PAUSED"
    assert (await call("resume_print_job", {"job_id": job_id}))["state"] == "RUNNING"
    token = await approve("stop", {})
    cancelled = await call("cancel_print_job", {"job_id": job_id, "approval_token": token})
    assert cancelled["state"] == "CANCELLED"
    assert (await call("archive_completed_job", {"job_id": job_id}))["job"]["state"] == "CANCELLED"


@pytest.mark.asyncio
async def test_mcp_tool_validation_branches(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    mcp = create_mcp(container)

    async def invalid(name: str, arguments: dict[str, Any], message: str) -> None:
        with pytest.raises(ToolError, match=message):
            await mcp._tool_manager.call_tool(name, arguments, convert_result=False)

    printer = registered_printer["id"]
    common = {"printer_id": printer, "job_id": "job", "approval_token": "token"}
    await invalid("set_fan", {"printer_id": printer, "fan": 0, "percent": 101}, "fan percent")
    await invalid("skip_objects", {**common, "object_ids": []}, "object IDs")
    await invalid("set_temperature", {**common, "target": "bed", "celsius": 121}, "temperature")
    await invalid("set_chamber", {**common, "celsius": 81}, "chamber target")
    await invalid("set_airduct", {**common, "channel": 5, "percent": 0}, "airduct")
    await invalid("jog_axis", {**common, "axis": "X", "millimeters": 51, "feedrate": 600}, "jog")
    await invalid(
        "load_filament", {**common, "slot": 40, "target_temperature": 220}, "filament load"
    )
    await invalid(
        "configure_ams",
        {**common, "ams_id": 8, "startup_read": True, "insertion_read": True},
        "AMS ID",
    )
    await invalid("read_ams_rfid", {**common, "ams_id": 0, "slot_id": 4}, "AMS/slot")
    await invalid(
        "dry_ams_filament", {**common, "ams_id": 0, "celsius": 50, "minutes": 0}, "drying"
    )
    await invalid("run_calibration", {**common, "option_mask": 16}, "option mask")
    await invalid("send_raw_gcode", {**common, "gcode": "x\x00"}, "exceeds policy")
    await invalid("set_detection_options", {**common, "options": {"unknown": True}}, "allowlisted")
