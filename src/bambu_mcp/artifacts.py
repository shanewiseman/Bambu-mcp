"""Content-addressed artifact ingestion, inspection, and archive validation."""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast

import trimesh
from defusedxml.ElementTree import fromstring
from sqlalchemy.orm import Session

from bambu_mcp.errors import NotFoundError, SafetyError, ValidationError
from bambu_mcp.models import Artifact
from bambu_mcp.schemas import ArtifactView, TransformSpec
from bambu_mcp.security import confined_path

ZIP_SIGNATURE = b"PK\x03\x04"
STL_SIGNATURE = b"solid"


def artifact_kind(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".gcode.3mf"):
        return "gcode-3mf"
    suffix = Path(lowered).suffix
    if suffix == ".3mf":
        return "3mf"
    if suffix == ".stl":
        return "stl"
    if suffix in {".jpg", ".jpeg"}:
        return "snapshot"
    raise ValidationError("only STL, 3MF, .gcode.3mf, and JPEG artifacts are accepted")


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    if name != filename or name in {"", ".", ".."} or "\\" in name or "\x00" in name:
        raise ValidationError("filename must be a plain basename")
    artifact_kind(name)
    return name


def media_type_for(filename: str) -> str:
    if filename.lower().endswith(".3mf"):
        return "model/3mf"
    if filename.lower().endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return mimetypes.guess_type(filename)[0] or "application/sla"


class ArchivePolicy:
    def __init__(self, max_entries: int, max_uncompressed_bytes: int) -> None:
        self.max_entries = max_entries
        self.max_uncompressed_bytes = max_uncompressed_bytes

    def validate(self, source: Path | BinaryIO, *, sliced: bool = False) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > self.max_entries:
                    raise ValidationError("archive entry count is outside policy")
                total = 0
                names: set[str] = set()
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in entry.filename
                        or "\x00" in entry.filename
                    ):
                        raise SafetyError("archive contains an unsafe path")
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise SafetyError("archive symlinks are not allowed")
                    total += entry.file_size
                    if total > self.max_uncompressed_bytes:
                        raise ValidationError("archive exceeds uncompressed size policy")
                    if entry.compress_size == 0 and entry.file_size > 0:
                        raise ValidationError("archive entry has an unsafe compression ratio")
                    if entry.compress_size and entry.file_size / entry.compress_size > 1_000:
                        raise ValidationError("archive entry has an unsafe compression ratio")
                    names.add(entry.filename)

                content_types = "[Content_Types].xml"
                if content_types not in names:
                    raise ValidationError("3MF is missing [Content_Types].xml")
                self._parse_xml(archive.read(content_types), content_types)

                model_files = sorted(name for name in names if name.lower().endswith(".model"))
                gcode_files = sorted(
                    name
                    for name in names
                    if name.startswith("Metadata/") and name.lower().endswith(".gcode")
                )
                if not sliced and not model_files:
                    raise ValidationError("3MF contains no model document")
                if sliced and not gcode_files:
                    raise ValidationError("sliced 3MF contains no plate G-code")
                for model_file in model_files:
                    self._parse_xml(archive.read(model_file), model_file)

                return {
                    "entries": len(entries),
                    "uncompressed_bytes": total,
                    "models": model_files,
                    "gcode_files": gcode_files,
                    "sliced": sliced,
                }
        except zipfile.BadZipFile as exc:
            raise ValidationError("artifact is not a valid ZIP/3MF archive") from exc

    @staticmethod
    def _parse_xml(content: bytes, name: str) -> None:
        try:
            fromstring(content)
        except Exception as exc:
            raise ValidationError(f"invalid hardened XML document: {name}") from exc


class ArtifactStore:
    """Store immutable uploads by SHA-256 and persist only safe metadata."""

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int,
        archive_policy: ArchivePolicy,
        import_root: Path | None = None,
        enable_local_imports: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.archive_policy = archive_policy
        self.import_root = import_root
        self.enable_local_imports = enable_local_imports
        self.root.mkdir(parents=True, exist_ok=True, mode=0o2770)
        self.root.chmod(0o2770)

    def path_for(self, artifact_id: str) -> Path:
        if len(artifact_id) != 64 or any(char not in "0123456789abcdef" for char in artifact_id):
            raise ValidationError("artifact ID must be a lowercase SHA-256 digest")
        return self.root / artifact_id[:2] / artifact_id

    def ingest_bytes(self, session: Session, filename: str, content: bytes) -> Artifact:
        return self.ingest_stream(session, filename, io.BytesIO(content))

    def ingest_stream(self, session: Session, filename: str, stream: BinaryIO) -> Artifact:
        name = safe_filename(filename)
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ValidationError("artifact exceeds configured upload limit")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise

        if size == 0:
            temporary_path.unlink(missing_ok=True)
            raise ValidationError("empty artifacts are not accepted")
        artifact_id = digest.hexdigest()
        destination = self.path_for(artifact_id)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o2770)
        destination.parent.chmod(0o2770)
        if destination.exists():
            temporary_path.unlink(missing_ok=True)
        else:
            os.replace(temporary_path, destination)
        destination.chmod(0o640)

        existing = session.get(Artifact, artifact_id)
        if existing:
            return existing
        kind = artifact_kind(name)
        metadata = self.inspect_path(destination, kind)
        artifact = Artifact(
            id=artifact_id,
            filename=name,
            media_type=media_type_for(name),
            size=size,
            kind=kind,
            metadata_json=metadata,
        )
        session.add(artifact)
        session.flush()
        return artifact

    def import_local(self, session: Session, candidate: Path) -> Artifact:
        if not self.enable_local_imports or self.import_root is None:
            raise SafetyError("local imports are disabled")
        source = confined_path(self.import_root, candidate)
        with source.open("rb") as stream:
            return self.ingest_stream(session, source.name, stream)

    def get(self, session: Session, artifact_id: str) -> Artifact:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None or not self.path_for(artifact_id).is_file():
            raise NotFoundError(f"artifact not found: {artifact_id}")
        return artifact

    def view(self, artifact: Artifact) -> ArtifactView:
        return ArtifactView(
            id=artifact.id,
            filename=artifact.filename,
            media_type=artifact.media_type,
            size=artifact.size,
            kind=artifact.kind,
            metadata=artifact.metadata_json,
            created_at=artifact.created_at,
        )

    def inspect_path(self, path: Path, kind: str) -> dict[str, Any]:
        if kind in {"3mf", "gcode-3mf"}:
            return self.archive_policy.validate(path, sliced=kind == "gcode-3mf")
        if kind == "snapshot":
            return {"format": "jpeg"}
        try:
            mesh = cast(Any, trimesh.load_mesh(path, file_type="stl"))
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.to_mesh()
            if not len(mesh.vertices) or not len(mesh.faces):
                raise ValidationError("STL mesh has no printable geometry")
            bounds = mesh.bounds.tolist()
            extents = mesh.extents.tolist()
            return {
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "watertight": bool(mesh.is_watertight),
                "bounds_mm": bounds,
                "extents_mm": extents,
                "volume_mm3": float(mesh.volume) if mesh.is_volume else None,
            }
        except Exception as exc:
            raise ValidationError("STL mesh could not be inspected") from exc

    def transform_stl(
        self,
        session: Session,
        artifact_id: str,
        transform: TransformSpec,
        *,
        repair: bool,
    ) -> Artifact:
        source = self.get(session, artifact_id)
        if source.kind != "stl":
            raise ValidationError("mesh transforms currently accept STL artifacts only")
        mesh = cast(Any, trimesh.load_mesh(self.path_for(source.id), file_type="stl"))
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh()
        if repair:
            mesh.update_faces(mesh.unique_faces())
            mesh.update_faces(mesh.nondegenerate_faces())
            mesh.remove_unreferenced_vertices()
            cast(Any, trimesh.repair.fix_normals)(mesh)
        mesh.apply_scale(transform.scale)
        matrix = cast(Any, trimesh.transformations.euler_matrix)(
            *(angle * 3.141592653589793 / 180 for angle in transform.rotate_degrees)
        )
        mesh.apply_transform(matrix)
        mesh.apply_translation(transform.translate_mm)
        data = mesh.export(file_type="stl")
        if isinstance(data, str):
            data = data.encode()
        if not isinstance(data, bytes):
            raise ValidationError("STL exporter returned an unsupported payload")
        stem = Path(source.filename).stem
        return self.ingest_bytes(session, f"{stem}-transformed.stl", data)

    def ingest_existing_file(self, session: Session, filename: str, path: Path) -> Artifact:
        with path.open("rb") as stream:
            artifact = self.ingest_stream(session, filename, stream)
        path.unlink(missing_ok=True)
        return artifact

    def copy_to(self, artifact_id: str, destination: Path) -> None:
        source = self.path_for(artifact_id)
        if not source.is_file():
            raise NotFoundError(f"artifact not found: {artifact_id}")
        shutil.copyfile(source, destination)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
