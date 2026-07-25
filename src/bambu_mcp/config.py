"""Runtime configuration with Docker-secret support and safe defaults."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def read_secret(value: str | None, file_path: Path | None) -> str | None:
    """Prefer a mounted secret file and reject empty secret material."""
    if file_path:
        secret = file_path.read_text(encoding="utf-8").strip()
        if not secret:
            raise ValueError(f"secret file is empty: {file_path}")
        return secret
    return value.strip() if value and value.strip() else None


class Settings(BaseSettings):
    """Service settings loaded from `BAMBU_MCP_*` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="BAMBU_MCP_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/bambu-mcp.db"
    artifact_root: Path = Path("./artifacts")
    import_root: Path | None = Path("/imports")
    protocol_matrix_path: Path = Path("./docs/protocol-capability-matrix.md")
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    public_base_url: str = "http://127.0.0.1:8000"
    api_key: str | None = None
    api_key_file: Path | None = None
    credential_key: str | None = None
    credential_key_file: Path | None = None
    bambu_ca_file: Path = Path("./certs/bambu-lab-ca.pem")
    slicer_url: str = "http://bambu-slicer:8080"
    slicer_version: str = "2.7.1.62"
    slicer_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    mqtt_ack_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    approval_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    artifact_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)
    archive_max_entries: int = Field(default=10_000, ge=1, le=100_000)
    archive_max_uncompressed_bytes: int = Field(
        default=2 * 1024 * 1024 * 1024,
        ge=1024,
    )
    allow_unverified_x2d_writes: bool = False
    enable_experimental_tools: bool = False
    enable_local_imports: bool = False
    allow_simulated_printers: bool = False
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("unsupported log level")
        return normalized

    @model_validator(mode="after")
    def require_auth_for_non_loopback(self) -> Settings:
        try:
            is_loopback = ipaddress.ip_address(self.bind_host).is_loopback
        except ValueError:
            is_loopback = self.bind_host == "localhost"
        if not is_loopback and not read_secret(self.api_key, self.api_key_file):
            raise ValueError("an API key is required when binding outside loopback")
        return self

    @model_validator(mode="after")
    def require_local_import_root(self) -> Settings:
        if self.enable_local_imports and self.import_root is None:
            raise ValueError("local imports require a configured import root")
        return self

    @property
    def resolved_api_key(self) -> str | None:
        return read_secret(self.api_key, self.api_key_file)

    @property
    def resolved_credential_key(self) -> str | None:
        return read_secret(self.credential_key, self.credential_key_file)

    def prepare_directories(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)


@lru_cache(maxsize=1)
def get_settings(**overrides: Any) -> Settings:
    """Return process settings; overrides exist primarily for adapters and tests."""
    return Settings(**overrides)
