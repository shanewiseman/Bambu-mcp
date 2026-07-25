from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import make_3mf, make_stl
from helpers import ingest
from sqlalchemy import select

from bambu_mcp.container import Container
from bambu_mcp.errors import ConflictError, SafetyError, SlicerError
from bambu_mcp.gateway import SimulatedGateway
from bambu_mcp.models import Approval, Job, JobState
from bambu_mcp.schemas import (
    MaterialRoute,
    PreparePrintRequest,
    PrintOptions,
    SliceSettings,
    TransformSpec,
)
from bambu_mcp.slicer import FakeSlicer


def request(
    printer_id: str,
    artifact_id: str,
    *,
    slice_settings: SliceSettings | None = None,
    transform: TransformSpec | None = None,
    repair: bool = False,
) -> PreparePrintRequest:
    return PreparePrintRequest(
        printer_id=printer_id,
        artifact_id=artifact_id,
        slice=slice_settings or SliceSettings(),
        print_options=PrintOptions(timelapse=True),
        transform=transform,
        repair=repair,
    )


@pytest.mark.asyncio
async def test_end_to_end_pipeline_approval_upload_start_and_archive(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    source_id = ingest(container, "box.stl", make_stl())
    prepared = await container.workflow.prepare_print_pipeline(
        request(registered_printer["id"], source_id)
    )
    assert prepared.state is JobState.AWAITING_APPROVAL
    assert prepared.output_artifact_id
    assert prepared.plan_digest
    assert prepared.plan["source_artifact_sha256"] == source_id
    assert prepared.plan["slicer"]["version"] == "2.7.1.62"
    events = container.workflow.job_events(prepared.id)
    assert [event["to_state"] for event in events] == [
        "INGESTED",
        "INSPECTED",
        "SLICED",
        "VALIDATED",
        "PREFLIGHTED",
        "AWAITING_APPROVAL",
    ]
    assert [job.id for job in container.workflow.queue()] == [prepared.id]

    approval = container.workflow.approve_print_plan(prepared.id)
    running = await container.workflow.execute_print_pipeline(prepared.id, approval.approval_token)
    assert running.state is JobState.RUNNING
    gateway = container.gateways._gateways[registered_printer["id"]]
    assert isinstance(gateway, SimulatedGateway)
    assert f"bambu-mcp-{prepared.id}.gcode.3mf" in await gateway.files()
    assert gateway.commands[-1][:2] == ("print", "project_file")
    assert gateway.commands[-1][2]["timelapse"] is True

    gateway.state["print"]["gcode_state"] = "FINISH"
    completed = await container.workflow.monitor_job(prepared.id)
    assert completed.state is JobState.SUCCEEDED
    assert container.workflow.queue() == []
    archive = container.workflow.completed_job_archive(prepared.id)
    assert archive["job"]["state"] == "SUCCEEDED"
    assert archive["source_artifact"]["id"] == source_id
    assert archive["output_artifact"]["id"] == prepared.output_artifact_id


@pytest.mark.asyncio
async def test_presliced_fallback_works_when_slicer_unavailable(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    assert isinstance(container.slicer, FakeSlicer)
    container.slicer.available = False
    source_id = ingest(container, "ready.gcode.3mf", make_3mf(sliced=True))
    prepared = await container.workflow.prepare_print_pipeline(
        request(registered_printer["id"], source_id)
    )
    assert prepared.output_artifact_id == source_id
    assert container.workflow.job_events(prepared.id)[2]["detail"]["mode"] == "pre-sliced"


@pytest.mark.asyncio
async def test_slicer_unavailable_and_dual_smoke_fail_closed(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    source_id = ingest(container, "box.stl", make_stl())
    assert isinstance(container.slicer, FakeSlicer)
    container.slicer.available = False
    with pytest.raises(ConflictError, match="not ready"):
        await container.workflow.prepare_print_pipeline(
            request(registered_printer["id"], source_id)
        )
    with container.database.session() as session:
        failed = session.scalars(select(Job).order_by(Job.created_at.desc())).first()
        assert failed and failed.state is JobState.FAILED

    container.slicer.available = True
    container.slicer.dual_nozzle = False
    with pytest.raises(SlicerError, match="dual-nozzle"):
        await container.workflow.prepare_print_pipeline(
            request(
                registered_printer["id"],
                source_id,
                slice_settings=SliceSettings(nozzle_diameters=(0.4, 0.4)),
            )
        )


@pytest.mark.asyncio
async def test_transform_repair_and_live_preflight_failures(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    source_id = ingest(container, "box.stl", make_stl())
    prepared = await container.workflow.prepare_print_pipeline(
        request(
            registered_printer["id"],
            source_id,
            transform=TransformSpec(scale=(2, 2, 2)),
            repair=True,
        )
    )
    with container.database.session() as session:
        job = session.get(Job, prepared.id)
        assert job and job.settings["effective_artifact_id"] != source_id

    busy = SimulatedGateway(state={"print": {"gcode_state": "RUNNING", "hms": []}})
    container.gateways._gateways[registered_printer["id"]] = busy
    with pytest.raises(ConflictError, match="not idle"):
        await container.workflow.prepare_print_pipeline(
            request(registered_printer["id"], source_id)
        )
    busy.state = {"print": {"gcode_state": "IDLE", "hms": [{"code": "x"}]}}
    with pytest.raises(ConflictError, match="HMS"):
        await container.workflow.prepare_print_pipeline(
            request(registered_printer["id"], source_id)
        )


@pytest.mark.asyncio
async def test_material_and_fts_preflight_boundaries(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    source_id = ingest(container, "box.stl", make_stl())
    ams_settings = SliceSettings(
        filament_profiles=("PLA",),
        material_routes=(MaterialRoute(filament_index=0, nozzle="left", ams_slot=0),),
    )
    await container.workflow.printer_status(registered_printer["id"])
    gateway = container.gateways._gateways[registered_printer["id"]]
    assert isinstance(gateway, SimulatedGateway)
    gateway.state = {"print": {"gcode_state": "IDLE", "hms": []}}
    with pytest.raises(ConflictError, match="requires AMS"):
        await container.workflow.prepare_print_pipeline(
            request(
                registered_printer["id"],
                source_id,
                slice_settings=ams_settings,
            )
        )

    fts_settings = SliceSettings(
        filament_profiles=("PLA",),
        material_routes=(
            MaterialRoute(
                filament_index=0,
                nozzle="left",
                external_spool=True,
                fts_channel=0,
            ),
        ),
    )
    with pytest.raises(SafetyError, match="FTS"):
        await container.workflow.prepare_print_pipeline(
            request(
                registered_printer["id"],
                source_id,
                slice_settings=fts_settings,
            )
        )


def test_approval_expiry_replay_and_plan_tamper(
    container: Container, registered_printer: dict[str, Any]
) -> None:
    source_id = ingest(container, "ready.gcode.3mf", make_3mf(sliced=True))

    async def prepare() -> Job:
        view = await container.workflow.prepare_print_pipeline(
            request(registered_printer["id"], source_id)
        )
        with container.database.session() as session:
            job = session.get(Job, view.id)
            assert job
            session.expunge(job)
            return job

    job = __import__("asyncio").run(prepare())
    approval = container.workflow.approve_print_plan(job.id)
    with container.database.session() as session:
        stored = session.scalar(select(Approval).where(Approval.job_id == job.id))
        assert stored
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(SafetyError, match="expired"):
        container.workflow._consume_approval(job.id, approval.approval_token, job.plan_digest or "")

    job = __import__("asyncio").run(prepare())
    approval = container.workflow.approve_print_plan(job.id)
    container.workflow._consume_approval(job.id, approval.approval_token, job.plan_digest or "")
    with pytest.raises(SafetyError, match="already"):
        container.workflow._consume_approval(job.id, approval.approval_token, job.plan_digest or "")
    with pytest.raises(SafetyError, match="invalid"):
        container.workflow._consume_approval(job.id, "wrong", job.plan_digest or "")

    job = __import__("asyncio").run(prepare())
    with container.database.session() as session:
        stored_job = session.get(Job, job.id)
        assert stored_job
        stored_job.plan = {**stored_job.plan, "plate": 99}
    with pytest.raises(SafetyError, match="no longer matches"):
        container.workflow.approve_print_plan(job.id)
