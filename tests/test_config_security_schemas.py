from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError as PydanticValidationError

from bambu_mcp.config import Settings, get_settings, read_secret
from bambu_mcp.errors import SafetyError, ValidationError
from bambu_mcp.schemas import (
    MaterialRoute,
    PrinterRegistration,
    SliceSettings,
    TransformSpec,
)
from bambu_mcp.security import (
    CredentialVault,
    canonical_digest,
    compare_api_key,
    confined_path,
    hash_token,
    issue_token,
    redact,
)


def test_read_secret_prefers_file_and_rejects_empty(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text(" from-file \n", encoding="utf-8")
    assert read_secret("inline", secret) == "from-file"
    assert read_secret(" inline ", None) == "inline"
    assert read_secret("  ", None) is None
    secret.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_secret(None, secret)


def test_settings_require_api_key_off_loopback_and_validate_log() -> None:
    with pytest.raises(PydanticValidationError, match="API key"):
        Settings(bind_host="0.0.0.0")
    assert Settings(bind_host="localhost").bind_host == "localhost"
    assert Settings(bind_host="0.0.0.0", api_key="key").resolved_api_key == "key"
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(PydanticValidationError, match="log level"):
        Settings(log_level="verbose")


def test_settings_prepare_directories_and_cache(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'nested' / 'db.sqlite'}",
        artifact_root=tmp_path / "objects",
    )
    settings.prepare_directories()
    assert settings.artifact_root.is_dir()
    assert (tmp_path / "nested").is_dir()
    get_settings.cache_clear()
    assert get_settings(database_url="sqlite:///:memory:") is get_settings(
        database_url="sqlite:///:memory:"
    )
    get_settings.cache_clear()


def test_credential_vault_round_trip_and_failures() -> None:
    vault = CredentialVault(Fernet.generate_key())
    encrypted = vault.encrypt("printer-code")
    assert encrypted != "printer-code"
    assert vault.decrypt(encrypted) == "printer-code"
    with pytest.raises(ValidationError, match="empty"):
        vault.encrypt("")
    with pytest.raises(ValidationError, match="Fernet"):
        CredentialVault("not-a-key")
    other = CredentialVault(Fernet.generate_key())
    with pytest.raises(SafetyError, match="decrypt"):
        other.decrypt(encrypted)


def test_api_key_digest_token_and_redaction() -> None:
    assert compare_api_key(None, None)
    assert compare_api_key("secret", "secret")
    assert not compare_api_key("secret", None)
    assert not compare_api_key("secret", "other")
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})
    token = issue_token()
    assert len(token) > 32
    assert len(hash_token(token)) == 64
    payload = {
        "password": "abc",
        "nested": [{"api_key": "def"}],
        "message": "access code=12345678 and token:xyz",
        "safe": 1,
    }
    redacted = redact(payload)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"][0]["api_key"] == "[REDACTED]"
    assert "12345678" not in redacted["message"]
    assert "xyz" not in redacted["message"]
    assert redacted["safe"] == 1


def test_confined_path_accepts_file_and_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "imports"
    root.mkdir()
    inside = root / "part.stl"
    inside.write_bytes(b"solid x")
    outside = tmp_path / "outside.stl"
    outside.write_bytes(b"solid y")
    assert confined_path(root, inside) == inside.resolve()
    with pytest.raises(SafetyError, match="outside"):
        confined_path(root, outside)
    with pytest.raises(FileNotFoundError):
        confined_path(root, root / "missing.stl")


def test_registration_and_transform_schemas() -> None:
    valid = PrinterRegistration(
        name="X2D", serial="ABCDEF12", host="printer.local", access_code="12345678"
    )
    assert valid.host == "printer.local"
    with pytest.raises(PydanticValidationError):
        PrinterRegistration(name="X", serial="ABCDEF12", host="https://bad", access_code="12345678")
    assert TransformSpec(scale=(1, 2, 3)).scale == (1, 2, 3)
    with pytest.raises(PydanticValidationError, match="scale"):
        TransformSpec(scale=(0, 1, 1))


def test_material_route_and_slice_schema_guards() -> None:
    route = MaterialRoute(filament_index=0, nozzle="left", ams_slot=3)
    assert route.ams_slot == 3
    with pytest.raises(PydanticValidationError, match="exactly one"):
        MaterialRoute(filament_index=0, nozzle="left")
    with pytest.raises(PydanticValidationError, match="exactly one"):
        MaterialRoute(
            filament_index=0,
            nozzle="left",
            ams_slot=0,
            external_spool=True,
        )
    assert SliceSettings(nozzle_diameters=(0.4, 0.6)).nozzle_diameters == (0.4, 0.6)
    with pytest.raises(PydanticValidationError, match="supported nozzle"):
        SliceSettings(nozzle_diameters=(0.5,))
    with pytest.raises(PydanticValidationError):
        SliceSettings(nozzle_diameters=(0.2, 0.4, 0.6))
