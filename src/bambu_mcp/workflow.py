"""Durable print workflows, approvals, preflight, and guarded printer actions."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bambu_mcp.artifacts import ArtifactStore
from bambu_mcp.capabilities import X2DAdapter, operation_named
from bambu_mcp.config import Settings
from bambu_mcp.database import Database
from bambu_mcp.errors import (
    ConflictError,
    NotFoundError,
    ProtocolError,
    SafetyError,
    ValidationError,
)
from bambu_mcp.gateway import GatewayPool, PrinterGateway
from bambu_mcp.models import Approval, Artifact, AuditEvent, Job, JobState, JobStep, Printer
from bambu_mcp.protocol.camera import snapshot
from bambu_mcp.schemas import (
    ApprovalView,
    CommandResult,
    JobView,
    PreparePrintRequest,
    PrinterRegistration,
    PrinterView,
    TransformSpec,
)
from bambu_mcp.security import CredentialVault, canonical_digest, hash_token, issue_token, redact
from bambu_mcp.slicer import Slicer

TERMINAL_STATES = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.INGESTED, JobState.FAILED, JobState.CANCELLED},
    JobState.INGESTED: {JobState.INSPECTED, JobState.FAILED, JobState.CANCELLED},
    JobState.INSPECTED: {JobState.SLICED, JobState.FAILED, JobState.CANCELLED},
    JobState.SLICED: {JobState.VALIDATED, JobState.FAILED, JobState.CANCELLED},
    JobState.VALIDATED: {JobState.PREFLIGHTED, JobState.FAILED, JobState.CANCELLED},
    JobState.PREFLIGHTED: {JobState.AWAITING_APPROVAL, JobState.FAILED, JobState.CANCELLED},
    JobState.AWAITING_APPROVAL: {JobState.UPLOADING, JobState.FAILED, JobState.CANCELLED},
    JobState.UPLOADING: {JobState.STARTING, JobState.FAILED, JobState.CANCELLED},
    JobState.STARTING: {JobState.RUNNING, JobState.FAILED, JobState.CANCELLED},
    JobState.RUNNING: {
        JobState.PAUSED,
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.PAUSED: {JobState.RUNNING, JobState.FAILED, JobState.CANCELLED},
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def job_view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        state=job.state,
        printer_id=job.printer_id,
        source_artifact_id=job.source_artifact_id,
        output_artifact_id=job.output_artifact_id,
        plan_digest=job.plan_digest,
        plan=job.plan,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def printer_view(printer: Printer) -> PrinterView:
    return PrinterView(
        id=printer.id,
        name=printer.name,
        serial=printer.serial,
        host=printer.host,
        model=printer.model,
        firmware=printer.firmware,
        developer_mode=printer.developer_mode,
        hardware_verified=printer.hardware_verified,
        capabilities=printer.capabilities,
    )


class WorkflowService:
    """Application service; all mutations are durable and audited."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        artifacts: ArtifactStore,
        slicer: Slicer,
        gateways: GatewayPool,
        vault: CredentialVault,
        adapter: X2DAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.artifacts = artifacts
        self.slicer = slicer
        self.gateways = gateways
        self.vault = vault
        self.adapter = adapter or X2DAdapter()

    def register_printer(self, request: PrinterRegistration) -> PrinterView:
        if request.model.upper() not in self.adapter.model_names:
            raise ValidationError("only the X2D/N6 adapter is enabled in this release")
        with self.database.session() as session:
            printer = Printer(
                name=request.name,
                serial=request.serial,
                host=str(request.host),
                model=request.model.upper(),
                encrypted_access_code=self.vault.encrypt(request.access_code),
                developer_mode=request.developer_mode,
                capabilities=self.adapter.capabilities(None),
            )
            session.add(printer)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise ConflictError("printer name or serial is already registered") from exc
            self._audit(session, "printer.register", "printer", printer.id, "success")
            return printer_view(printer)

    def list_printers(self) -> list[PrinterView]:
        with self.database.session() as session:
            printers = session.scalars(select(Printer).order_by(Printer.name)).all()
            return [printer_view(printer) for printer in printers]

    def get_printer(self, printer_id: str) -> PrinterView:
        with self.database.session() as session:
            return printer_view(self._printer(session, printer_id))

    def get_job(self, job_id: str) -> JobView:
        with self.database.session() as session:
            return job_view(self._job(session, job_id))

    async def discover_capabilities(self, printer_id: str) -> PrinterView:
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
        gateway = await self._gateway(printer)
        result = await gateway.command("info", "get_version")
        if result.result != "success":
            raise ProtocolError(f"version discovery failed: {result.reason}")
        firmware = self._firmware_from_result(result) or None
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            printer.firmware = firmware
            printer.capabilities = self.adapter.capabilities(firmware)
            self._audit(
                session,
                "printer.discover_capabilities",
                "printer",
                printer.id,
                "success",
                {"firmware": firmware, "evidence": "live-read"},
            )
            return printer_view(printer)

    async def printer_status(self, printer_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
        gateway = await self._gateway(printer)
        state = await gateway.status()
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            printer.state = state
            self._audit(session, "printer.status", "printer", printer.id, "success")
        return cast(dict[str, Any], redact(state))

    async def prepare_print_pipeline(self, request: PreparePrintRequest) -> JobView:
        """Inspect, slice or accept pre-sliced input, validate, and live-preflight."""
        with self.database.session() as session:
            printer = self._printer(session, request.printer_id)
            artifact = self.artifacts.get(session, request.artifact_id)
            if request.slice.printer_profile.upper() not in self.adapter.model_names:
                raise ValidationError("slice profile does not target X2D/N6")
            job = Job(
                printer_id=printer.id,
                source_artifact_id=artifact.id,
                settings={
                    "request": request.model_dump(mode="json"),
                    "effective_artifact_id": artifact.id,
                },
            )
            session.add(job)
            session.flush()
            self._audit(session, "job.create", "job", job.id, "success")
            job_id = job.id

        try:
            self._advance(job_id, JobState.INGESTED, {"artifact_id": request.artifact_id})
            effective = self._inspect_and_transform(job_id, request)
            self._advance(
                job_id,
                JobState.INSPECTED,
                {"artifact_id": effective.id, "metadata": effective.metadata_json},
            )

            if effective.kind == "gcode-3mf":
                with self.database.session() as session:
                    job = self._job(session, job_id)
                    job.output_artifact_id = effective.id
                    self._transition(session, job, JobState.SLICED, {"mode": "pre-sliced"})
            else:
                if effective.kind not in {"stl", "3mf"}:
                    raise ValidationError("source artifact cannot be sliced")
                if not await self.slicer.ready():
                    raise ConflictError("slicer sidecar is not ready; use a pre-sliced .gcode.3mf")
                output_path = await self.slicer.slice(
                    job_id=job_id,
                    artifact_id=effective.id,
                    filename=effective.filename,
                    kind=effective.kind,
                    settings=request.slice,
                )
                with self.database.session() as session:
                    output = self.artifacts.ingest_existing_file(
                        session,
                        f"{Path(effective.filename).stem}.gcode.3mf",
                        output_path,
                    )
                    job = self._job(session, job_id)
                    job.output_artifact_id = output.id
                    self._transition(
                        session,
                        job,
                        JobState.SLICED,
                        {"slicer_version": self.slicer.version, "artifact_id": output.id},
                    )

            mapping = self.adapter.material_mapping(request.slice)
            with self.database.session() as session:
                printer = self._printer(session, request.printer_id)
                if (
                    any(route.fts_channel is not None for route in request.slice.material_routes)
                    and not printer.hardware_verified
                ):
                    raise SafetyError("FTS routing remains fail-closed until hardware verification")
            with self.database.session() as session:
                job = self._job(session, job_id)
                if not job.output_artifact_id:
                    raise ConflictError("workflow has no sliced artifact")
                output = self.artifacts.get(session, job.output_artifact_id)
                validation = self.artifacts.archive_policy.validate(
                    self.artifacts.path_for(output.id),
                    sliced=True,
                )
                self._transition(
                    session,
                    job,
                    JobState.VALIDATED,
                    {"archive": validation, "material_mapping": mapping},
                )
                printer = self._printer(session, job.printer_id)

            gateway = await self._gateway(printer)
            live_state = await gateway.status()
            self._preflight(live_state, mapping)
            with self.database.session() as session:
                job = self._job(session, job_id)
                printer = self._printer(session, job.printer_id)
                output = self.artifacts.get(session, job.output_artifact_id or "")
                source = self.artifacts.get(session, job.source_artifact_id)
                self._transition(
                    session,
                    job,
                    JobState.PREFLIGHTED,
                    {"live_state": self._preflight_summary(live_state)},
                )
                plan = {
                    "schema_version": 1,
                    "job_id": job.id,
                    "source_artifact_sha256": source.id,
                    "slice_artifact_sha256": output.id,
                    "printer": {
                        "id": printer.id,
                        "serial": printer.serial,
                        "model": printer.model,
                        "firmware": printer.firmware,
                        "hardware_verified": printer.hardware_verified,
                    },
                    "slicer": {
                        "version": self.slicer.version,
                        "printer_profile": request.slice.printer_profile,
                        "process_profile": request.slice.process_profile,
                        "filament_profiles": request.slice.filament_profiles,
                    },
                    "plate": request.slice.plate,
                    "bed_type": request.slice.bed_type,
                    "nozzle_diameters": request.slice.nozzle_diameters,
                    "material_mapping": mapping,
                    "print_options": request.print_options.model_dump(mode="json"),
                    "artifact_validation": output.metadata_json,
                }
                digest = canonical_digest(plan)
                job.plan = plan
                job.plan_digest = digest
                self._transition(
                    session,
                    job,
                    JobState.AWAITING_APPROVAL,
                    {"plan_digest": digest},
                )
                self._audit(
                    session,
                    "job.prepare",
                    "job",
                    job.id,
                    "success",
                    {"plan_digest": digest},
                )
                return job_view(job)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            raise

    async def submit_stl_pipeline(self, request: PreparePrintRequest) -> JobView:
        return await self.prepare_print_pipeline(request)

    def approve_print_plan(self, job_id: str) -> ApprovalView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state is not JobState.AWAITING_APPROVAL or not job.plan_digest:
                raise ConflictError("job is not awaiting approval")
            if canonical_digest(job.plan) != job.plan_digest:
                raise SafetyError("stored print plan no longer matches its digest")
            return self._issue_approval(session, job, job.plan_digest, "job.approve")

    def approve_guarded_action(
        self,
        job_id: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> ApprovalView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state in TERMINAL_STATES:
                raise ConflictError("guarded actions cannot target a terminal job")
            catalogued = operation_named(
                operation,
                experimental_enabled=self.settings.enable_experimental_tools,
            )
            if catalogued.risk.value not in {"guarded", "experimental"}:
                raise ValidationError("this operation does not require a guarded approval")
            digest = self._action_digest(job, operation, parameters or {})
            return self._issue_approval(session, job, digest, "action.approve")

    async def execute_print_pipeline(self, job_id: str, approval_token: str) -> JobView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state is not JobState.AWAITING_APPROVAL or not job.plan_digest:
                raise ConflictError("job is not ready to execute")
            if canonical_digest(job.plan) != job.plan_digest:
                raise SafetyError("print plan changed after approval preparation")
            digest = job.plan_digest
        self._consume_approval(job_id, approval_token, digest)

        try:
            with self.database.session() as session:
                job = self._job(session, job_id)
                printer = self._printer(session, job.printer_id)
                self._require_write(printer)
                if job.plan.get("printer", {}).get("firmware") != printer.firmware:
                    raise SafetyError("printer firmware changed after preflight")
                output = self.artifacts.get(session, job.output_artifact_id or "")
                output_path = self.artifacts.path_for(output.id)
                plan = job.plan

            gateway = await self._gateway(printer)
            live_state = await gateway.status()
            self._preflight(live_state, plan["material_mapping"])
            remote_name = f"bambu-mcp-{job_id}.gcode.3mf"
            self._advance(job_id, JobState.UPLOADING, {"remote_name": remote_name})
            await gateway.upload(remote_name, output_path)
            self._advance(job_id, JobState.STARTING, {"upload_verified": True})
            print_options = plan["print_options"]
            parameters = {
                "param": f"Metadata/plate_{plan['plate']}.gcode",
                "project_id": "0",
                "profile_id": "0",
                "task_id": "0",
                "subtask_id": "0",
                "subtask_name": "",
                "file": "",
                "url": f"ftp:///{remote_name}",
                "md5": "",
                "timelapse": print_options["timelapse"],
                "bed_type": plan["bed_type"],
                "bed_levelling": print_options["bed_levelling"],
                "flow_cali": print_options["flow_calibration"],
                "vibration_cali": print_options["vibration_calibration"],
                "layer_inspect": print_options["layer_inspection"],
                **plan["material_mapping"],
            }
            result = await gateway.command("print", "project_file", parameters)
            self._require_success(result)
            with self.database.session() as session:
                job = self._job(session, job_id)
                self._transition(
                    session,
                    job,
                    JobState.RUNNING,
                    {"sequence_id": result.sequence_id, "acknowledged": True},
                )
                self._audit(session, "job.execute", "job", job.id, "success")
                return job_view(job)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            raise

    async def run_operation(
        self,
        *,
        printer_id: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
        job_id: str | None = None,
        approval_token: str | None = None,
    ) -> CommandResult:
        catalogued = operation_named(
            operation,
            experimental_enabled=self.settings.enable_experimental_tools,
        )
        params = parameters or {}
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            if catalogued.risk.value != "read-only":
                self._require_write(printer)
        gateway = await self._gateway(printer)
        if catalogued.risk.value in {"guarded", "experimental"}:
            if not job_id or not approval_token:
                raise SafetyError("guarded operations require a job-bound one-use approval")
            with self.database.session() as session:
                job = self._job(session, job_id)
                if job.printer_id != printer_id:
                    raise SafetyError("approval job belongs to a different printer")
                digest = self._action_digest(job, operation, params)
            self._consume_approval(job_id, approval_token, digest)
        result = await gateway.command(catalogued.family, catalogued.command, params)
        self._require_success(result)
        with self.database.session() as session:
            self._audit(
                session,
                f"printer.{operation}",
                "printer",
                printer_id,
                "success",
                {"sequence_id": result.sequence_id, "risk": catalogued.risk.value},
            )
        return result

    async def pause_and_diagnose(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state is not JobState.RUNNING:
                raise ConflictError("only a running job can be paused")
            printer_id = job.printer_id
        result = await self.run_operation(printer_id=printer_id, operation="pause", job_id=job_id)
        with self.database.session() as session:
            job = self._job(session, job_id)
            self._transition(session, job, JobState.PAUSED, {"sequence_id": result.sequence_id})
        state = await self.printer_status(printer_id)
        print_state = state.get("print", {})
        return {
            "job_id": job_id,
            "state": "PAUSED",
            "hms": print_state.get("hms", []),
            "print_error": print_state.get("print_error", 0),
        }

    async def resume_job(self, job_id: str) -> JobView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state is not JobState.PAUSED:
                raise ConflictError("only a paused job can be resumed")
            printer_id = job.printer_id
        result = await self.run_operation(printer_id=printer_id, operation="resume", job_id=job_id)
        with self.database.session() as session:
            job = self._job(session, job_id)
            self._transition(session, job, JobState.RUNNING, {"sequence_id": result.sequence_id})
            return job_view(job)

    async def cancel_job(self, job_id: str, approval_token: str) -> JobView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            printer_id = job.printer_id
        await self.run_operation(
            printer_id=printer_id,
            operation="stop",
            job_id=job_id,
            approval_token=approval_token,
        )
        with self.database.session() as session:
            job = self._job(session, job_id)
            self._transition(session, job, JobState.CANCELLED, {"safe_stop": True})
            return job_view(job)

    async def monitor_job(self, job_id: str) -> JobView:
        with self.database.session() as session:
            job = self._job(session, job_id)
            printer = self._printer(session, job.printer_id)
        gateway = await self._gateway(printer)
        state = await gateway.status()
        reported = str(state.get("print", {}).get("gcode_state", "")).upper()
        target = {
            "RUNNING": JobState.RUNNING,
            "PAUSE": JobState.PAUSED,
            "PAUSED": JobState.PAUSED,
            "FINISH": JobState.SUCCEEDED,
            "FAILED": JobState.FAILED,
        }.get(reported)
        with self.database.session() as session:
            job = self._job(session, job_id)
            if target and target is not job.state:
                self._transition(session, job, target, {"reported_gcode_state": reported})
            return job_view(job)

    def queue(self, printer_id: str | None = None) -> list[JobView]:
        with self.database.session() as session:
            query = select(Job).where(Job.state.not_in(TERMINAL_STATES)).order_by(Job.created_at)
            if printer_id:
                query = query.where(Job.printer_id == printer_id)
            return [job_view(job) for job in session.scalars(query).all()]

    def job_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._job(session, job_id)
            steps = session.scalars(
                select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id)
            ).all()
            return [
                {
                    "id": step.id,
                    "from_state": step.from_state,
                    "to_state": step.to_state,
                    "detail": redact(step.detail),
                    "created_at": step.created_at.isoformat(),
                }
                for step in steps
            ]

    def completed_job_archive(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = self._job(session, job_id)
            if job.state not in TERMINAL_STATES:
                raise ConflictError("job is not complete")
            source = self.artifacts.get(session, job.source_artifact_id)
            output = (
                self.artifacts.get(session, job.output_artifact_id)
                if job.output_artifact_id
                else None
            )
            return {
                "job": job_view(job).model_dump(mode="json"),
                "source_artifact": self.artifacts.view(source).model_dump(mode="json"),
                "output_artifact": (
                    self.artifacts.view(output).model_dump(mode="json") if output else None
                ),
                "events": self.job_events(job_id),
            }

    async def printer_files(self, printer_id: str) -> list[str]:
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
        gateway = await self._gateway(printer)
        return await gateway.files()

    async def camera_snapshot(self, printer_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            access_code = self.vault.decrypt(printer.encrypted_access_code)
            host = printer.host
        image = await snapshot(host, access_code)
        with self.database.session() as session:
            artifact = self.artifacts.ingest_bytes(session, f"{printer_id}-snapshot.jpg", image)
            self._audit(
                session,
                "printer.camera_snapshot",
                "printer",
                printer_id,
                "success",
                {"artifact_id": artifact.id},
            )
            return self.artifacts.view(artifact).model_dump(mode="json")

    async def upload_artifact_to_printer(
        self,
        printer_id: str,
        artifact_id: str,
        filename: str,
        job_id: str,
        approval_token: str,
    ) -> None:
        params = {"artifact_id": artifact_id, "filename": filename}
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            job = self._job(session, job_id)
            artifact = self.artifacts.get(session, artifact_id)
            self._require_write(printer)
            digest = self._action_digest(job, "file_upload", params)
            source = self.artifacts.path_for(artifact.id)
        gateway = await self._gateway(printer)
        self._consume_approval(job_id, approval_token, digest)
        await gateway.upload(filename, source)
        with self.database.session() as session:
            self._audit(session, "printer.file_upload", "printer", printer_id, "success", params)

    async def run_raw_mqtt(
        self,
        *,
        printer_id: str,
        family: str,
        command: str,
        parameters: dict[str, Any],
        job_id: str,
        approval_token: str,
    ) -> CommandResult:
        operation_named("raw_mqtt", experimental_enabled=self.settings.enable_experimental_tools)
        if family == "upgrade" or (family == "system" and command == "get_access_code"):
            raise SafetyError("firmware and credential commands are never exposed")
        action = {"family": family, "command": command, "parameters": parameters}
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            job = self._job(session, job_id)
            self._require_write(printer)
            digest = self._action_digest(job, "raw_mqtt", action)
        gateway = await self._gateway(printer)
        self._consume_approval(job_id, approval_token, digest)
        result = await gateway.command(family, command, parameters)
        self._require_success(result)
        return result

    async def delete_printer_file(
        self,
        printer_id: str,
        filename: str,
        job_id: str,
        approval_token: str,
    ) -> None:
        params = {"filename": filename}
        with self.database.session() as session:
            printer = self._printer(session, printer_id)
            job = self._job(session, job_id)
            self._require_write(printer)
            digest = self._action_digest(job, "file_delete", params)
        gateway = await self._gateway(printer)
        self._consume_approval(job_id, approval_token, digest)
        await gateway.delete(filename)
        with self.database.session() as session:
            self._audit(session, "printer.file_delete", "printer", printer_id, "success", params)

    def _inspect_and_transform(self, job_id: str, request: PreparePrintRequest) -> Artifact:
        with self.database.session() as session:
            job = self._job(session, job_id)
            effective = self.artifacts.get(session, job.settings["effective_artifact_id"])
            if request.transform or request.repair:
                effective = self.artifacts.transform_stl(
                    session,
                    effective.id,
                    request.transform or TransformSpec(),
                    repair=request.repair,
                )
                settings = dict(job.settings)
                settings["effective_artifact_id"] = effective.id
                job.settings = settings
            return effective

    def _advance(self, job_id: str, target: JobState, detail: dict[str, Any]) -> None:
        with self.database.session() as session:
            self._transition(session, self._job(session, job_id), target, detail)

    def _transition(
        self,
        session: Session,
        job: Job,
        target: JobState,
        detail: dict[str, Any],
    ) -> None:
        if target not in ALLOWED_TRANSITIONS[job.state]:
            raise ConflictError(f"invalid job transition: {job.state.value} -> {target.value}")
        previous = job.state
        job.state = target
        job.error = detail.get("error") if target is JobState.FAILED else job.error
        session.add(
            JobStep(
                job_id=job.id,
                from_state=previous.value,
                to_state=target.value,
                detail=redact(detail),
            )
        )
        session.flush()

    def _fail_job(self, job_id: str, reason: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None or job.state in TERMINAL_STATES:
                return
            self._transition(session, job, JobState.FAILED, {"error": reason})
            self._audit(session, "job.fail", "job", job.id, "failed", {"error": reason})

    def _issue_approval(
        self,
        session: Session,
        job: Job,
        digest: str,
        audit_action: str,
    ) -> ApprovalView:
        token = issue_token()
        expires = datetime.now(UTC) + timedelta(seconds=self.settings.approval_ttl_seconds)
        session.add(
            Approval(
                job_id=job.id,
                plan_digest=digest,
                token_hash=hash_token(token),
                expires_at=expires,
            )
        )
        self._audit(
            session,
            audit_action,
            "job",
            job.id,
            "success",
            {"digest": digest, "expires_at": expires.isoformat()},
        )
        return ApprovalView(
            job_id=job.id,
            approval_token=token,
            plan_digest=digest,
            expires_at=expires,
        )

    def _consume_approval(self, job_id: str, token: str, expected_digest: str) -> None:
        token_digest = hash_token(token)
        with self.database.session() as session:
            approval = session.scalar(
                select(Approval).where(
                    Approval.job_id == job_id,
                    Approval.token_hash == token_digest,
                )
            )
            if approval is None:
                raise SafetyError("approval token is invalid")
            if approval.used_at is not None:
                raise SafetyError("approval token has already been used")
            if as_utc(approval.expires_at) <= datetime.now(UTC):
                raise SafetyError("approval token has expired")
            if not hmac.compare_digest(approval.plan_digest, expected_digest):
                raise SafetyError("approval is bound to a different immutable action")
            approval.used_at = datetime.now(UTC)
            self._audit(session, "approval.consume", "job", job_id, "success")

    @staticmethod
    def _action_digest(job: Job, operation: str, parameters: dict[str, Any]) -> str:
        return canonical_digest(
            {
                "schema_version": 1,
                "job_id": job.id,
                "printer_id": job.printer_id,
                "job_state": job.state.value,
                "operation": operation,
                "parameters": parameters,
            }
        )

    async def _gateway(self, printer: Printer) -> PrinterGateway:
        return await self.gateways.get(
            printer,
            self.vault.decrypt(printer.encrypted_access_code),
        )

    def _require_write(self, printer: Printer) -> None:
        self.adapter.require_write_allowed(
            model=printer.model,
            hardware_verified=printer.hardware_verified,
            allow_unverified_x2d_writes=self.settings.allow_unverified_x2d_writes,
            developer_mode=printer.developer_mode,
        )

    @staticmethod
    def _preflight(state: dict[str, Any], mapping: dict[str, Any]) -> None:
        print_state = state.get("print", state)
        gcode_state = str(print_state.get("gcode_state", "UNKNOWN")).upper()
        if gcode_state not in {"IDLE", "FINISH"}:
            raise ConflictError(f"printer is not idle: {gcode_state}")
        if print_state.get("hms"):
            raise ConflictError("printer reports active HMS faults")
        if mapping.get("use_ams") and "ams" not in print_state:
            raise ConflictError("print plan requires AMS but no AMS inventory was reported")

    @staticmethod
    def _preflight_summary(state: dict[str, Any]) -> dict[str, Any]:
        print_state = state.get("print", state)
        return {
            "gcode_state": print_state.get("gcode_state"),
            "hms_count": len(print_state.get("hms", [])),
            "has_ams": "ams" in print_state,
            "active_tool": print_state.get("active_tool"),
            "nozzle_diameter": print_state.get("nozzle_diameter"),
        }

    @staticmethod
    def _require_success(result: CommandResult) -> None:
        if result.result != "success":
            raise ProtocolError(f"printer rejected {result.command}: {result.reason}")

    @staticmethod
    def _firmware_from_result(result: CommandResult) -> str:
        for module in result.payload.get("module", []):
            if module.get("name") == "ota":
                return str(module.get("sw_ver", ""))
        return ""

    @staticmethod
    def _printer(session: Session, printer_id: str) -> Printer:
        printer = session.get(Printer, printer_id)
        if printer is None:
            raise NotFoundError(f"printer not found: {printer_id}")
        return printer

    @staticmethod
    def _job(session: Session, job_id: str) -> Job:
        job = session.get(Job, job_id)
        if job is None:
            raise NotFoundError(f"job not found: {job_id}")
        return job

    @staticmethod
    def _audit(
        session: Session,
        action: str,
        target_type: str,
        target_id: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                detail=redact(detail or {}),
            )
        )
