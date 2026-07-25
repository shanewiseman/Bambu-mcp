from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest
from conftest import make_3mf, make_stl

from bambu_mcp.artifacts import (
    ArchivePolicy,
    ArtifactStore,
    artifact_kind,
    hash_file,
    media_type_for,
    safe_filename,
)
from bambu_mcp.database import Database
from bambu_mcp.errors import NotFoundError, SafetyError, ValidationError
from bambu_mcp.schemas import TransformSpec


def store(tmp_path: Path, *, max_bytes: int = 1_000_000) -> tuple[Database, ArtifactStore]:
    database = Database(f"sqlite:///{tmp_path / 'db.sqlite'}")
    database.create_schema()
    artifacts = ArtifactStore(
        tmp_path / "artifacts",
        max_bytes=max_bytes,
        archive_policy=ArchivePolicy(20, 1_000_000),
        import_root=tmp_path / "imports",
        enable_local_imports=True,
    )
    return database, artifacts


def test_artifact_names_kinds_and_media() -> None:
    assert artifact_kind("part.STL") == "stl"
    assert artifact_kind("project.3mf") == "3mf"
    assert artifact_kind("plate.gcode.3mf") == "gcode-3mf"
    assert artifact_kind("snap.jpeg") == "snapshot"
    assert media_type_for("part.3mf") == "model/3mf"
    assert media_type_for("snap.jpg") == "image/jpeg"
    assert safe_filename("part.stl") == "part.stl"
    for invalid in ("../part.stl", "/part.stl", r"a\b.stl", "", "part.obj", "a\x00.stl"):
        with pytest.raises(ValidationError):
            safe_filename(invalid)


def test_ingest_deduplicates_inspects_and_copies(tmp_path: Path) -> None:
    database, artifacts = store(tmp_path)
    with database.session() as session:
        first = artifacts.ingest_bytes(session, "box.stl", make_stl())
        second = artifacts.ingest_bytes(session, "renamed.stl", make_stl())
        assert first.id == second.id
        assert first.metadata_json["watertight"] is True
        assert first.metadata_json["extents_mm"] == pytest.approx([10, 20, 30])
        view = artifacts.view(first)
        assert view.id == first.id
    destination = tmp_path / "copy.stl"
    artifacts.copy_to(first.id, destination)
    assert hash_file(destination) == first.id
    stored = artifacts.path_for(first.id)
    assert stored.is_file()
    assert stat.S_IMODE(artifacts.root.stat().st_mode) == 0o2770
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o2770
    assert stat.S_IMODE(stored.stat().st_mode) == 0o640
    with pytest.raises(ValidationError, match="SHA-256"):
        artifacts.path_for("bad")
    with pytest.raises(NotFoundError):
        artifacts.copy_to("0" * 64, destination)


def test_ingest_limits_empty_invalid_and_missing(tmp_path: Path) -> None:
    database, artifacts = store(tmp_path, max_bytes=10)
    with database.session() as session:
        with pytest.raises(ValidationError, match="empty"):
            artifacts.ingest_bytes(session, "x.stl", b"")
        with pytest.raises(ValidationError, match="upload limit"):
            artifacts.ingest_bytes(session, "x.stl", b"x" * 11)
        with pytest.raises(ValidationError, match="inspected"):
            artifacts.ingest_bytes(session, "x.stl", b"not stl")
        with pytest.raises(NotFoundError):
            artifacts.get(session, "0" * 64)


def test_3mf_and_snapshot_ingestion(tmp_path: Path) -> None:
    database, artifacts = store(tmp_path)
    with database.session() as session:
        model = artifacts.ingest_bytes(session, "model.3mf", make_3mf())
        sliced = artifacts.ingest_bytes(session, "model.gcode.3mf", make_3mf(sliced=True))
        snapshot = artifacts.ingest_bytes(session, "camera.jpg", b"\xff\xd8\xff\xd9")
        assert model.metadata_json["models"] == ["3D/3dmodel.model"]
        assert sliced.metadata_json["gcode_files"] == ["Metadata/plate_1.gcode"]
        assert snapshot.metadata_json == {"format": "jpeg"}


def test_transform_and_repair_stl(tmp_path: Path) -> None:
    database, artifacts = store(tmp_path)
    with database.session() as session:
        source = artifacts.ingest_bytes(session, "box.stl", make_stl())
        output = artifacts.transform_stl(
            session,
            source.id,
            TransformSpec(
                scale=(2, 1, 1),
                translate_mm=(5, 0, 0),
                rotate_degrees=(0, 0, 90),
            ),
            repair=True,
        )
        assert output.id != source.id
        assert sorted(output.metadata_json["extents_mm"]) == pytest.approx([20, 20, 30])
        model = artifacts.ingest_bytes(session, "model.3mf", make_3mf())
        with pytest.raises(ValidationError, match="STL"):
            artifacts.transform_stl(session, model.id, TransformSpec(), repair=False)


def test_local_import_policy_and_cleanup(tmp_path: Path) -> None:
    database, artifacts = store(tmp_path)
    import_root = tmp_path / "imports"
    import_root.mkdir()
    source = import_root / "box.stl"
    source.write_bytes(make_stl())
    with database.session() as session:
        imported = artifacts.import_local(session, source)
        assert imported.id == hash_file(source)
    artifacts.enable_local_imports = False
    with database.session() as session, pytest.raises(SafetyError, match="disabled"):
        artifacts.import_local(session, source)
    generated = tmp_path / "generated.gcode.3mf"
    generated.write_bytes(make_3mf(sliced=True))
    with database.session() as session:
        output = artifacts.ingest_existing_file(session, "out.gcode.3mf", generated)
        assert output.kind == "gcode-3mf"
    assert not generated.exists()


def archive_bytes(entries: list[tuple[str, bytes, int | None]]) -> io.BytesIO:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
    stream.seek(0)
    return stream


def test_archive_policy_failure_boundaries() -> None:
    policy = ArchivePolicy(4, 1_000)
    with pytest.raises(ValidationError, match="ZIP"):
        policy.validate(io.BytesIO(b"bad"))
    with pytest.raises(ValidationError, match="entry count"):
        policy.validate(archive_bytes([]))
    traversal = archive_bytes([("[Content_Types].xml", b"<Types/>", None), ("../evil", b"x", None)])
    with pytest.raises(SafetyError, match="unsafe path"):
        policy.validate(traversal)
    absolute = archive_bytes([("[Content_Types].xml", b"<Types/>", None), ("/evil", b"x", None)])
    with pytest.raises(SafetyError, match="unsafe path"):
        policy.validate(absolute)
    symlink = archive_bytes(
        [("[Content_Types].xml", b"<Types/>", None), ("link", b"x", stat.S_IFLNK)]
    )
    with pytest.raises(SafetyError, match="symlink"):
        policy.validate(symlink)
    too_large = ArchivePolicy(4, 5)
    with pytest.raises(ValidationError, match="uncompressed"):
        too_large.validate(
            archive_bytes(
                [
                    ("[Content_Types].xml", b"<Types/>", None),
                    ("3D/a.model", b"<model/>", None),
                ]
            )
        )


def test_archive_required_members_and_xml() -> None:
    policy = ArchivePolicy(10, 10_000)
    with pytest.raises(ValidationError, match="Content_Types"):
        policy.validate(archive_bytes([("3D/a.model", b"<model/>", None)]))
    with pytest.raises(ValidationError, match="no model"):
        policy.validate(archive_bytes([("[Content_Types].xml", b"<Types/>", None)]))
    with pytest.raises(ValidationError, match="plate G-code"):
        policy.validate(
            archive_bytes(
                [
                    ("[Content_Types].xml", b"<Types/>", None),
                    ("3D/a.model", b"<model/>", None),
                ]
            ),
            sliced=True,
        )
    with pytest.raises(ValidationError, match="hardened XML"):
        policy.validate(
            archive_bytes(
                [
                    ("[Content_Types].xml", b"<Types>", None),
                    ("3D/a.model", b"<model/>", None),
                ]
            )
        )
    entity = b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><model>&y;</model>'
    with pytest.raises(ValidationError, match="hardened XML"):
        policy.validate(
            archive_bytes(
                [
                    ("[Content_Types].xml", b"<Types/>", None),
                    ("3D/a.model", entity, None),
                ]
            )
        )
