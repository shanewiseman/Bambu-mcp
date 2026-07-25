"""Validate that built artifacts preserve the Python/Studio license boundary."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ALLOWED_PACKAGE_ROOTS = {"bambu_mcp"}
WHEEL_FORBIDDEN_PARTS = {"certs", "profiles", "BambuStudio", "bambu-studio"}
BINARY_SUFFIXES = {".AppImage", ".deb", ".dll", ".dylib", ".exe", ".rpm", ".so"}
REQUIRED_MIGRATION_FILES = {
    "bambu_mcp/migrations/__init__.py",
    "bambu_mcp/migrations/env.py",
    "bambu_mcp/migrations/script.py.mako",
    "bambu_mcp/migrations/versions/__init__.py",
    "bambu_mcp/migrations/versions/0001_initial_schema.py",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = sorted(root.glob("*.whl"))
    sdists = sorted(root.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        fail("expected exactly one wheel and one source distribution")

    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        top_level = {name.split("/", maxsplit=1)[0] for name in names}
        dist_info_roots = {
            name
            for name in top_level
            if name.startswith("bambu_mcp-") and name.endswith(".dist-info")
        }
        if len(dist_info_roots) != 1:
            fail("expected exactly one bambu_mcp-*.dist-info wheel root")
        allowed_roots = ALLOWED_PACKAGE_ROOTS | dist_info_roots
        if unexpected_roots := top_level - allowed_roots:
            fail(f"unexpected wheel roots: {sorted(unexpected_roots)}")
        if any(part in name.split("/") for name in names for part in WHEEL_FORBIDDEN_PARTS):
            fail("wheel includes Studio, certificate, or profile material")
        missing_migrations = REQUIRED_MIGRATION_FILES - set(names)
        if missing_migrations:
            fail(f"wheel is missing packaged migrations: {sorted(missing_migrations)}")

    with tarfile.open(sdists[0], "r:gz") as archive:
        paths = [PurePosixPath(name) for name in archive.getnames()]
        profile_payloads = [
            str(path) for path in paths if "profiles" in path.parts and path.name != ".gitkeep"
        ]
        bundled_binaries = [
            str(path)
            for path in paths
            if path.suffix in BINARY_SUFFIXES
            or any(part in {"BambuStudio", "bambu-studio"} for part in path.parts)
        ]
        if profile_payloads:
            fail(f"source distribution includes profile payloads: {profile_payloads}")
        if bundled_binaries:
            fail(f"source distribution includes Studio/binary material: {bundled_binaries}")

    print(f"validated {wheels[0].name} and {sdists[0].name}")


if __name__ == "__main__":
    main()
