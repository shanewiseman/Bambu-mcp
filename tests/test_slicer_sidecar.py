from __future__ import annotations

import asyncio
import errno
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import make_3mf
from fastapi.testclient import TestClient

from bambu_mcp import slicer_sidecar
from bambu_mcp.errors import SlicerError
from bambu_mcp.schemas import SliceSettings
from bambu_mcp.slicer import FakeSlicer, HttpSlicer


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.is_success = status_code < 400

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if not self.is_success:
            request = httpx.Request("POST", "http://slicer/slice")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("bad", request=request, response=response)


class FakeHTTPClient:
    get_response = FakeResponse({"ready": True, "version": "2.7.1.62"})
    post_response = FakeResponse({"version": "2.7.1.62"})
    last_timeout: float | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        type(self).last_timeout = kwargs.get("timeout")

    async def __aenter__(self) -> FakeHTTPClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str) -> FakeResponse:
        assert url.endswith("/readyz")
        return self.get_response

    async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        assert url.endswith("/slice")
        assert json["artifact_id"] == "a" * 64
        return self.post_response


@pytest.mark.asyncio
async def test_http_slicer_ready_and_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeHTTPClient)
    FakeHTTPClient.get_response = FakeResponse({"ready": True, "version": "2.7.1.62"})
    slicer = HttpSlicer("http://slicer/", tmp_path, version="2.7.1.62", timeout=3.5)
    assert await slicer.ready()
    assert FakeHTTPClient.last_timeout == 3.5
    output = tmp_path / "work" / "job" / "output.gcode.3mf"
    output.parent.mkdir(parents=True)
    output.write_bytes(make_3mf(sliced=True))
    assert (
        await slicer.slice(
            job_id="job",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )
        == output
    )
    with pytest.raises(SlicerError, match="unsafe"):
        await slicer.slice(
            job_id="../bad",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )


@pytest.mark.asyncio
async def test_http_slicer_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeHTTPClient)
    slicer = HttpSlicer("http://slicer", tmp_path, version="2.7.1.62", timeout=10)
    FakeHTTPClient.get_response = FakeResponse({"ready": True, "version": "wrong"})
    assert not await slicer.ready()
    FakeHTTPClient.get_response = FakeResponse({"ready": False, "version": "2.7.1.62"})
    assert not await slicer.ready()
    FakeHTTPClient.get_response = FakeResponse({"version": "2.7.1.62"})
    assert not await slicer.ready()
    FakeHTTPClient.get_response = FakeResponse({"ready": True, "version": "2.7.1.62"})
    for invalid_payload in ([], "not an object"):
        FakeHTTPClient.post_response = FakeResponse(invalid_payload)
        with pytest.raises(SlicerError, match="invalid response"):
            await slicer.slice(
                job_id="job",
                artifact_id="a" * 64,
                filename="part.stl",
                kind="stl",
                settings=SliceSettings(),
            )
    FakeHTTPClient.post_response = FakeResponse({"version": "wrong"})
    with pytest.raises(SlicerError, match="unexpected version"):
        await slicer.slice(
            job_id="job",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )
    FakeHTTPClient.post_response = FakeResponse({"version": "2.7.1.62"}, 500)
    with pytest.raises(SlicerError, match="request failed"):
        await slicer.slice(
            job_id="job",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )
    FakeHTTPClient.post_response = FakeResponse({"version": "2.7.1.62"})
    with pytest.raises(SlicerError, match="did not produce"):
        await slicer.slice(
            job_id="job",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )


@pytest.mark.asyncio
async def test_fake_slicer_contract(tmp_path: Path) -> None:
    slicer = FakeSlicer(tmp_path, make_3mf(sliced=True))
    assert await slicer.ready()
    output = await slicer.slice(
        job_id="job",
        artifact_id="a" * 64,
        filename="part.stl",
        kind="stl",
        settings=SliceSettings(),
    )
    assert output.is_file()
    assert slicer.requests[0]["filename"] == "part.stl"
    slicer.dual_nozzle = False
    with pytest.raises(SlicerError, match="dual-nozzle"):
        await slicer.slice(
            job_id="dual",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(nozzle_diameters=(0.4, 0.4)),
        )
    slicer.available = False
    assert not await slicer.ready()
    with pytest.raises(SlicerError, match="unavailable"):
        await slicer.slice(
            job_id="off",
            artifact_id="a" * 64,
            filename="part.stl",
            kind="stl",
            settings=SliceSettings(),
        )


def sidecar_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = tmp_path / "artifacts"
    profiles = tmp_path / "profiles"
    for group in ("machine", "process", "filament"):
        path = profiles / group
        path.mkdir(parents=True)
    (profiles / "machine" / "X2D.json").write_text("{}", encoding="utf-8")
    (profiles / "process" / "0.20mm Standard.json").write_text("{}", encoding="utf-8")
    (profiles / "filament" / "Generic PLA.json").write_text("{}", encoding="utf-8")
    source = artifacts / ("a" * 2) / ("a" * 64)
    source.parent.mkdir(parents=True)
    source.write_bytes(b"stl")
    monkeypatch.setattr(slicer_sidecar, "ARTIFACT_ROOT", artifacts)
    monkeypatch.setattr(slicer_sidecar, "PROFILE_ROOT", profiles)


@pytest.mark.parametrize(
    ("layout", "expected"),
    (
        ("work-root-symlink", "unsafe work directory"),
        ("job-file", "File exists"),
        ("stale-directory", "unexpected directory"),
    ),
)
def test_sidecar_rejects_unsafe_workspace_layouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, expected: str
) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(slicer_sidecar, "DUAL_SMOKE_OK", True)
    work_root = slicer_sidecar.ARTIFACT_ROOT / "work"
    if layout == "work-root-symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        work_root.symlink_to(outside, target_is_directory=True)
    elif layout == "job-file":
        work_root.mkdir()
        (work_root / "job").write_bytes(b"not a directory")
    else:
        stale = work_root / "job" / "source.stl"
        stale.mkdir(parents=True)
    payload = {
        "job_id": "job",
        "artifact_id": "a" * 64,
        "filename": "part.stl",
        "kind": "stl",
        "settings": SliceSettings().model_dump(mode="json"),
    }
    with TestClient(slicer_sidecar.app) as client:
        response = client.post("/slice", json=payload)

    assert response.status_code == 422
    assert expected in response.text


def test_sidecar_paths_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    assert slicer_sidecar.profile_path("machine", "X2D").name == "X2D.json"
    assert slicer_sidecar.artifact_path("a" * 64).is_file()
    with pytest.raises(ValueError, match="unsafe"):
        slicer_sidecar.profile_path("machine", "../bad")
    with pytest.raises(ValueError, match="not mounted"):
        slicer_sidecar.profile_path("machine", "missing")
    with pytest.raises(ValueError, match="unavailable"):
        slicer_sidecar.artifact_path("b" * 64)
    request = slicer_sidecar.SliceRequest(
        job_id="job",
        artifact_id="a" * 64,
        filename="part.stl",
        kind="stl",
        settings=SliceSettings(),
    )
    command = slicer_sidecar.build_command(request, tmp_path / "source.stl", tmp_path / "out.3mf")
    assert "--orient" in command
    assert "--load-settings" in command
    assert command[command.index("--enable-support") + 1] == "0"
    assert "--clone-objects" not in command
    assert "--repetitions" not in command
    assert command[-1].endswith("source.stl")


def test_sidecar_command_maps_support_and_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    source = tmp_path / "source.stl"
    output = tmp_path / "out.3mf"

    stl_request = slicer_sidecar.SliceRequest(
        job_id="stl-job",
        artifact_id="a" * 64,
        filename="part.stl",
        kind="stl",
        settings=SliceSettings(supports=True, orient=False, copies=3),
    )
    stl_command = slicer_sidecar.build_command(stl_request, source, output)
    assert stl_command[stl_command.index("--enable-support") + 1] == "1"
    assert stl_command[stl_command.index("--clone-objects") + 1] == "3"
    assert "--repetitions" not in stl_command
    assert "--orient" not in stl_command

    project_request = stl_request.model_copy(update={"filename": "project.3mf", "kind": "3mf"})
    project_command = slicer_sidecar.build_command(project_request, tmp_path / "source.3mf", output)
    assert project_command[project_command.index("--repetitions") + 1] == "3"
    assert "--clone-objects" not in project_command


class SidecarProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"stdout", self.stderr

    def kill(self) -> None:
        self.killed = True


@pytest.mark.asyncio
async def test_binary_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "studio"
    monkeypatch.setattr(slicer_sidecar, "BINARY", binary)
    slicer_home = tmp_path / "slicer-home"
    monkeypatch.setattr(slicer_sidecar, "SLICER_HOME", str(slicer_home))
    monkeypatch.setenv("PATH", "/test/bin")
    assert not await slicer_sidecar.binary_version()
    binary.write_text("binary", encoding="utf-8")

    async def create(*args: Any, **kwargs: Any) -> SidecarProcess:
        assert args == (str(binary), "--help")
        assert kwargs["env"] == {"HOME": str(slicer_home), "PATH": "/test/bin"}
        return SidecarProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    assert await slicer_sidecar.binary_version()

    async def timeout(awaitable: Any, **kwargs: Any) -> Any:
        assert kwargs["timeout"] == 30
        awaitable.close()
        raise TimeoutError

    process = SidecarProcess()

    async def timed_create(*args: Any, **kwargs: Any) -> SidecarProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", timed_create)
    monkeypatch.setattr(asyncio, "wait_for", timeout)
    assert not await slicer_sidecar.binary_version()
    assert process.killed


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.ENOEXEC])
def test_readyz_fails_closed_when_binary_cannot_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    binary = tmp_path / "studio"
    binary.write_text("not executable", encoding="utf-8")
    monkeypatch.setattr(slicer_sidecar, "BINARY", binary)

    async def reject_launch(*args: Any, **kwargs: Any) -> SidecarProcess:
        raise OSError(error_number, "cannot execute Studio")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", reject_launch)
    with TestClient(slicer_sidecar.app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["ready"] is False


@pytest.mark.parametrize(("job_mode", "expected_status"), [(0o2770, 200), (0o2750, 422)])
def test_sidecar_tolerates_nonowner_chmod_only_for_safe_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_mode: int,
    expected_status: int,
) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(slicer_sidecar, "DUAL_SMOKE_OK", True)
    work_root = slicer_sidecar.ARTIFACT_ROOT / "work"
    work = work_root / "job"
    work.mkdir(parents=True)
    original_chmod = Path.chmod
    original_chmod(work_root, 0o2770)
    original_chmod(work, job_mode)
    protected = {work_root.resolve(), work.resolve()}

    def reject_nonowner_chmod(path: Path, mode: int) -> None:
        if path.resolve() in protected and mode == 0o2770:
            raise PermissionError("not owner")
        original_chmod(path, mode)

    async def create(*args: Any, **kwargs: Any) -> SidecarProcess:
        output = work / "output.gcode.3mf"
        output.write_bytes(make_3mf(sliced=True))
        return SidecarProcess()

    monkeypatch.setattr(Path, "chmod", reject_nonowner_chmod)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    payload = {
        "job_id": "job",
        "artifact_id": "a" * 64,
        "filename": "part.stl",
        "kind": "stl",
        "settings": SliceSettings().model_dump(mode="json"),
    }
    with TestClient(slicer_sidecar.app) as client:
        response = client.post("/slice", json=payload)

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["metadata"]["sliced"] is True
    else:
        assert "unsafe work directory permissions" in response.text


def test_sidecar_http_health_ready_and_dual_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar_environment(tmp_path, monkeypatch)

    async def ready() -> bool:
        return True

    monkeypatch.setattr(slicer_sidecar, "binary_version", ready)
    monkeypatch.setattr(slicer_sidecar, "DUAL_SMOKE_OK", False)
    with TestClient(slicer_sidecar.app) as client:
        assert client.get("/healthz").json()["version"] == "2.7.1.62"
        assert client.get("/readyz").json()["ready"] is True
        payload = {
            "job_id": "dual",
            "artifact_id": "a" * 64,
            "filename": "part.stl",
            "kind": "stl",
            "settings": SliceSettings(nozzle_diameters=(0.4, 0.4)).model_dump(mode="json"),
        }
        assert client.post("/slice", json=payload).status_code == 409


def test_sidecar_slice_success_and_process_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(slicer_sidecar, "DUAL_SMOKE_OK", True)
    slicer_home = tmp_path / "slicer-home"
    monkeypatch.setattr(slicer_sidecar, "SLICER_HOME", str(slicer_home))
    monkeypatch.setenv("PATH", "/test/bin")
    current_job = "success"

    async def create(*args: Any, **kwargs: Any) -> SidecarProcess:
        assert kwargs["env"] == {"HOME": str(slicer_home), "PATH": "/test/bin"}
        output = slicer_sidecar.ARTIFACT_ROOT / "work" / current_job / "output.gcode.3mf"
        output.write_bytes(make_3mf(sliced=True))
        return SidecarProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    payload = {
        "job_id": current_job,
        "artifact_id": "a" * 64,
        "filename": "part.stl",
        "kind": "stl",
        "settings": SliceSettings().model_dump(mode="json"),
    }
    with TestClient(slicer_sidecar.app) as client:
        response = client.post("/slice", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["sliced"] is True
        work = slicer_sidecar.ARTIFACT_ROOT / "work" / current_job
        assert stat.S_IMODE(work.stat().st_mode) == 0o2770
        assert stat.S_IMODE((work / "source.stl").stat().st_mode) == 0o640
        assert stat.S_IMODE((work / "output.gcode.3mf").stat().st_mode) == 0o640

        (work / "source.stl").write_bytes(b"stale source")
        (work / "output.gcode.3mf").write_bytes(b"stale output")
        response = client.post("/slice", json=payload)
        assert response.status_code == 200, response.text
        assert (work / "source.stl").read_bytes() == b"stl"
        assert response.json()["metadata"]["sliced"] is True

        outside = tmp_path / "outside"
        outside.mkdir()
        linked = slicer_sidecar.ARTIFACT_ROOT / "work" / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        payload["job_id"] = "linked"
        response = client.post("/slice", json=payload)
        assert response.status_code == 422
        assert "unsafe work directory" in response.text

    current_job = "failure"

    async def fail(*args: Any, **kwargs: Any) -> SidecarProcess:
        return SidecarProcess(1, b"failed slice")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)
    payload["job_id"] = current_job
    with TestClient(slicer_sidecar.app) as client:
        response = client.post("/slice", json=payload)
        assert response.status_code == 422
        assert "failed slice" in response.text
