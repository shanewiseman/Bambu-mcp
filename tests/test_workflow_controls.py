from __future__ import annotations

from typing import Any

import pytest
from conftest import make_3mf
from helpers import ingest

from bambu_mcp.container import Container
from bambu_mcp.errors import ConflictError, NotFoundError, SafetyError
from bambu_mcp.gateway import SimulatedGateway
from bambu_mcp.models import JobState
from bambu_mcp.schemas import PreparePrintRequest


async def running_job(container: Container, printer_id: str) -> str:
    artifact_id = ingest(container, "ready.gcode.3mf", make_3mf(sliced=True))
    prepared = await container.workflow.prepare_print_pipeline(
        PreparePrintRequest(printer_id=printer_id, artifact_id=artifact_id)
    )
    approval = container.workflow.approve_print_plan(prepared.id)
    await container.workflow.execute_print_pipeline(prepared.id, approval.approval_token)
    return prepared.id


@pytest.mark.asyncio
async def test_pause_resume_diagnose_and_monitor(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    job_id = await running_job(container, registered_printer["id"])
    diagnosed = await container.workflow.pause_and_diagnose(job_id)
    assert diagnosed["state"] == "PAUSED"
    assert container.workflow.get_job(job_id).state is JobState.PAUSED
    resumed = await container.workflow.resume_job(job_id)
    assert resumed.state is JobState.RUNNING
    with pytest.raises(ConflictError, match="paused"):
        await container.workflow.resume_job(job_id)
    with pytest.raises(NotFoundError, match="missing"):
        await container.workflow.pause_and_diagnose("missing")

    gateway = container.gateways._gateways[registered_printer["id"]]
    assert isinstance(gateway, SimulatedGateway)
    gateway.state["print"]["gcode_state"] = "PAUSE"
    assert (await container.workflow.monitor_job(job_id)).state is JobState.PAUSED
    gateway.state["print"]["gcode_state"] = "RUNNING"
    assert (await container.workflow.monitor_job(job_id)).state is JobState.RUNNING
    gateway.state["print"]["gcode_state"] = "FAILED"
    assert (await container.workflow.monitor_job(job_id)).state is JobState.FAILED


@pytest.mark.asyncio
async def test_guarded_action_approval_and_cancel(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    job_id = await running_job(container, registered_printer["id"])
    with pytest.raises(SafetyError, match="one-use"):
        await container.workflow.run_operation(
            printer_id=registered_printer["id"], operation="stop", job_id=job_id
        )
    approval = container.workflow.approve_guarded_action(job_id, "stop", {})
    cancelled = await container.workflow.cancel_job(job_id, approval.approval_token)
    assert cancelled.state is JobState.CANCELLED
    with pytest.raises(ConflictError, match="terminal"):
        container.workflow.approve_guarded_action(job_id, "stop", {})
    with pytest.raises(ConflictError, match="not complete"):
        container.workflow.completed_job_archive(
            await running_job(container, registered_printer["id"])
        )


@pytest.mark.asyncio
async def test_guarded_approval_binds_parameters_and_printer(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    job_id = await running_job(container, registered_printer["id"])
    params = {"param": "M140 S50"}
    approval = container.workflow.approve_guarded_action(job_id, "temperature", params)
    with pytest.raises(SafetyError, match="different"):
        await container.workflow.run_operation(
            printer_id=registered_printer["id"],
            operation="temperature",
            parameters={"param": "M140 S60"},
            job_id=job_id,
            approval_token=approval.approval_token,
        )

    other = container.workflow.register_printer(
        __import__("bambu_mcp.schemas", fromlist=["PrinterRegistration"]).PrinterRegistration(
            name="Other",
            serial="N6OTHER123",
            host="192.0.2.20",
            access_code="12345678",
            developer_mode=True,
        )
    )
    approval = container.workflow.approve_guarded_action(job_id, "temperature", params)
    with pytest.raises(SafetyError, match="different printer"):
        await container.workflow.run_operation(
            printer_id=other.id,
            operation="temperature",
            parameters=params,
            job_id=job_id,
            approval_token=approval.approval_token,
        )


@pytest.mark.asyncio
async def test_guarded_file_upload_delete(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    job_id = await running_job(container, registered_printer["id"])
    artifact_id = ingest(container, "extra.gcode.3mf", make_3mf(sliced=True))
    filename = "extra.gcode.3mf"
    upload_params = {"artifact_id": artifact_id, "filename": filename}
    approval = container.workflow.approve_guarded_action(job_id, "file_upload", upload_params)
    await container.workflow.upload_artifact_to_printer(
        registered_printer["id"],
        artifact_id,
        filename,
        job_id,
        approval.approval_token,
    )
    assert filename in await container.workflow.printer_files(registered_printer["id"])
    delete_params = {"filename": filename}
    approval = container.workflow.approve_guarded_action(job_id, "file_delete", delete_params)
    await container.workflow.delete_printer_file(
        registered_printer["id"], filename, job_id, approval.approval_token
    )
    assert filename not in await container.workflow.printer_files(registered_printer["id"])


@pytest.mark.asyncio
async def test_raw_mqtt_feature_gate_and_forbidden_commands(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    job_id = await running_job(container, registered_printer["id"])
    action = {"family": "print", "command": "custom", "parameters": {"x": 1}}
    with pytest.raises(SafetyError, match="disabled"):
        container.workflow.approve_guarded_action(job_id, "raw_mqtt", action)
    container.settings.enable_experimental_tools = True
    approval = container.workflow.approve_guarded_action(job_id, "raw_mqtt", action)
    result = await container.workflow.run_raw_mqtt(
        printer_id=registered_printer["id"],
        family="print",
        command="custom",
        parameters={"x": 1},
        job_id=job_id,
        approval_token=approval.approval_token,
    )
    assert result.result == "success"
    approval = container.workflow.approve_guarded_action(
        job_id,
        "raw_mqtt",
        {"family": "upgrade", "command": "start", "parameters": {}},
    )
    with pytest.raises(SafetyError, match="never exposed"):
        await container.workflow.run_raw_mqtt(
            printer_id=registered_printer["id"],
            family="upgrade",
            command="start",
            parameters={},
            job_id=job_id,
            approval_token=approval.approval_token,
        )


@pytest.mark.asyncio
async def test_registration_listing_status_discovery_and_operation_failure(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    assert container.workflow.get_printer(registered_printer["id"]).name == "Workshop X2D"
    assert len(container.workflow.list_printers()) == 1
    status = await container.workflow.printer_status(registered_printer["id"])
    assert status["print"]["gcode_state"] == "IDLE"
    discovered = await container.workflow.discover_capabilities(registered_printer["id"])
    assert discovered.capabilities["dual_nozzle"] is True
    gateway = container.gateways._gateways[registered_printer["id"]]
    assert isinstance(gateway, SimulatedGateway)
    gateway.fail_commands.add("pause")
    with pytest.raises(Exception, match="rejected"):
        await container.workflow.run_operation(
            printer_id=registered_printer["id"], operation="pause"
        )
