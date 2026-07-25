from __future__ import annotations

import stat
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from bambu_mcp.database import Database


def test_migration_upgrade_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("BAMBU_MCP_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert stat.S_IMODE((tmp_path / "migration.db").stat().st_mode) == 0o600
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "printers",
        "artifacts",
        "jobs",
        "job_steps",
        "approvals",
        "audit_events",
    } <= tables
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_database_upgrade_uses_packaged_revision_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.db"
    database = Database(f"sqlite:///{database_path}")

    database.upgrade_schema()
    database.upgrade_schema()

    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    database.engine.dispose()


def test_runtime_container_records_packaged_revision(container) -> None:
    with container.database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
