from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
import trimesh
from cryptography.fernet import Fernet

from bambu_mcp.config import Settings
from bambu_mcp.container import Container, build_container
from bambu_mcp.schemas import PrinterRegistration
from bambu_mcp.slicer import FakeSlicer


def make_3mf(
    *,
    sliced: bool = False,
    entries: dict[str, bytes] | None = None,
    model_xml: bytes | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        archive.writestr(
            "3D/3dmodel.model",
            model_xml
            or b'<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"></model>',
        )
        if sliced:
            archive.writestr("Metadata/plate_1.gcode", b"; generated fixture\nG28\n")
            archive.writestr("Metadata/slice_info.config", b"<config />")
        for name, content in (entries or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def make_stl() -> bytes:
    data = trimesh.creation.box(extents=(10, 20, 30)).export(file_type="stl")
    assert isinstance(data, bytes)
    return data


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'bambu.db'}",
        artifact_root=tmp_path / "artifacts",
        import_root=tmp_path / "imports",
        protocol_matrix_path=Path("docs/protocol-capability-matrix.md"),
        credential_key=Fernet.generate_key().decode(),
        api_key="test-api-key",
        allow_simulated_printers=True,
        allow_unverified_x2d_writes=True,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    slicer = FakeSlicer(settings.artifact_root, make_3mf(sliced=True))
    created = build_container(settings, slicer=slicer)
    yield created
    created.database.engine.dispose()


@pytest.fixture
def registered_printer(container: Container) -> dict[str, Any]:
    return container.workflow.register_printer(
        PrinterRegistration(
            name="Workshop X2D",
            serial="N6TEST123456",
            host="192.0.2.10",
            access_code="12345678",
            model="X2D",
            developer_mode=True,
        )
    ).model_dump(mode="json")
