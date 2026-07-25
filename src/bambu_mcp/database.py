"""Database lifecycle and restart recovery helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from bambu_mcp.models import Base, Job, JobState, JobStep

INTERRUPTED_STATES = {
    JobState.UPLOADING,
    JobState.STARTING,
}


def create_db_engine(database_url: str) -> Engine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def harden_sqlite_file(database_url: str | URL) -> None:
    """Limit a file-backed SQLite database to its owning service account."""
    url = make_url(database_url) if isinstance(database_url, str) else database_url
    database = url.database
    if url.get_backend_name() != "sqlite" or not database or database == ":memory:":
        return
    database_path = Path(database)
    if database_path.is_file():
        database_path.chmod(0o600)


class Database:
    """Own the SQLAlchemy engine and transaction-scoped sessions."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_db_engine(database_url)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        harden_sqlite_file(self.engine.url)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def recover_interrupted_jobs(self) -> list[str]:
        """Fail ambiguous in-flight writes after restart; monitoring remains resumable."""
        recovered: list[str] = []
        with self.session_factory.begin() as session:
            jobs = session.scalars(select(Job).where(Job.state.in_(INTERRUPTED_STATES))).all()
            for job in jobs:
                previous = job.state
                job.state = JobState.FAILED
                job.error = "service restarted during a non-idempotent printer operation"
                session.add(
                    JobStep(
                        job_id=job.id,
                        from_state=previous.value,
                        to_state=JobState.FAILED.value,
                        detail={"recovery": "fail-closed"},
                    )
                )
                recovered.append(job.id)
        return recovered
