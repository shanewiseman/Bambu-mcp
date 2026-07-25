from __future__ import annotations

import stat
from pathlib import Path

from bambu_mcp.database import Database
from bambu_mcp.models import Artifact, Job, JobState, Printer


def test_recover_interrupted_jobs_and_keep_running(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'db.sqlite'}")
    database.create_schema()
    with database.session() as session:
        printer = Printer(
            id="p",
            name="P",
            serial="SERIAL1",
            host="192.0.2.1",
            encrypted_access_code="encrypted",
        )
        artifact = Artifact(
            id="a" * 64,
            filename="x.stl",
            media_type="application/sla",
            size=1,
            kind="stl",
        )
        session.add_all([printer, artifact])
        for state in (JobState.UPLOADING, JobState.STARTING, JobState.RUNNING):
            session.add(
                Job(
                    id=state.value,
                    state=state,
                    printer_id=printer.id,
                    source_artifact_id=artifact.id,
                )
            )
    recovered = database.recover_interrupted_jobs()
    assert set(recovered) == {"UPLOADING", "STARTING"}
    with database.session() as session:
        assert session.get(Job, "UPLOADING").state is JobState.FAILED
        assert "restarted" in session.get(Job, "STARTING").error
        assert session.get(Job, "RUNNING").state is JobState.RUNNING
    assert database.recover_interrupted_jobs() == []


def test_sqlite_database_is_owner_only(tmp_path: Path) -> None:
    database_path = tmp_path / "state.sqlite"
    database = Database(f"sqlite:///{database_path}")

    database.create_schema()
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600

    database_path.chmod(0o644)
    database.create_schema()
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    database.engine.dispose()
