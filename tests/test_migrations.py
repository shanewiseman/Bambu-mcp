from __future__ import annotations

import stat
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
