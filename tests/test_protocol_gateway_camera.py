from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

import pytest

from bambu_mcp.errors import ProtocolError, ValidationError
from bambu_mcp.gateway import GatewayPool, SimulatedGateway
from bambu_mcp.models import Printer
from bambu_mcp.protocol import camera
from bambu_mcp.protocol.ftps import FTPSClient, remote_filename


def test_remote_filename() -> None:
    assert remote_filename("plate.gcode.3mf") == "plate.gcode.3mf"
    for invalid in ("", "../x", "/x", "a\\b", ".", "a\x00b"):
        with pytest.raises(ValidationError, match="basename"):
            remote_filename(invalid)


class FakeFTP:
    def __init__(self) -> None:
        self.data = b""
        self.deleted: list[str] = []
        self.closed = False
        self.close_count = 0
        self.fail = False
        self.fail_quit = False
        self.quit_count = 0

    def storbinary(self, command: str, source: io.BytesIO) -> None:
        assert command == "STOR plate.3mf"
        if self.fail:
            raise OSError("broken")
        self.data = source.read()

    def size(self, name: str) -> int:
        assert name == "plate.3mf"
        return len(self.data)

    def nlst(self) -> list[str]:
        if self.fail:
            raise OSError("broken")
        return ["z", "a"]

    def delete(self, name: str) -> None:
        if self.fail:
            raise OSError("broken")
        self.deleted.append(name)

    def quit(self) -> None:
        self.quit_count += 1
        if self.fail_quit:
            raise OSError("QUIT failed")
        self.closed = True

    def close(self) -> None:
        self.close_count += 1
        self.closed = True


def test_ftps_client_upload_list_delete_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FTPSClient("192.0.2.10", "12345678", Path("certs/bambu-lab-ca.pem"))
    fake = FakeFTP()
    monkeypatch.setattr(client, "_connect", lambda: fake)
    source = io.BytesIO(b"payload")
    client.upload("plate.3mf", source)
    assert fake.data == b"payload"
    assert fake.closed
    assert fake.quit_count == 1
    assert fake.close_count == 0
    fake.closed = False
    assert client.list_files() == ["a", "z"]
    assert fake.quit_count == 2
    client.delete("plate.3mf")
    assert fake.deleted == ["plate.3mf"]
    assert fake.quit_count == 3
    fake.fail = True
    with pytest.raises(ProtocolError, match="upload"):
        client.upload("plate.3mf", io.BytesIO(b"x"))
    with pytest.raises(ProtocolError, match="listing"):
        client.list_files()
    with pytest.raises(ProtocolError, match="delete"):
        client.delete("plate.3mf")


def test_ftps_list_and_delete_close_when_quit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FTPSClient("192.0.2.10", "12345678", Path("certs/bambu-lab-ca.pem"))
    fake = FakeFTP()
    fake.fail_quit = True
    monkeypatch.setattr(client, "_connect", lambda: fake)

    assert client.list_files() == ["a", "z"]
    client.delete("plate.3mf")

    assert fake.quit_count == 2
    assert fake.close_count == 2


def test_ftps_upload_nonseekable_and_from_current_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonSeekable(io.BytesIO):
        def tell(self) -> int:
            raise io.UnsupportedOperation("not seekable")

        def seek(self, *args: Any, **kwargs: Any) -> int:
            raise io.UnsupportedOperation("not seekable")

    client = FTPSClient("192.0.2.10", "12345678", Path("certs/bambu-lab-ca.pem"))
    fake = FakeFTP()
    monkeypatch.setattr(client, "_connect", lambda: fake)

    client.upload("plate.3mf", NonSeekable(b"streamed"))
    assert fake.data == b"streamed"

    positioned = io.BytesIO(b"prefix-payload")
    positioned.seek(len(b"prefix-"))
    client.upload("plate.3mf", positioned)
    assert fake.data == b"payload"


def test_ftps_upload_size_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FTPSClient("192.0.2.10", "12345678", Path("certs/bambu-lab-ca.pem"))
    fake = FakeFTP()
    monkeypatch.setattr(client, "_connect", lambda: fake)
    monkeypatch.setattr(fake, "size", lambda name: 999)
    with pytest.raises(ProtocolError, match="size verification"):
        client.upload("plate.3mf", io.BytesIO(b"x"))


def test_camera_url_validation() -> None:
    assert camera.camera_url("192.0.2.1", "12345678").startswith("rtsps://bblp:")
    assert camera.camera_url("2001:db8::42", "12345678") == (
        "rtsps://bblp:12345678@[2001:db8::42]:322/streaming/live/1"
    )
    with pytest.raises(ValidationError, match="literal"):
        camera.camera_url("printer.local", "12345678")
    with pytest.raises(ValidationError, match="unsafe"):
        camera.camera_url("192.0.2.1", "bad@code")


class FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"jpeg", stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_snapshot_wraps_process_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*args: Any, **kwargs: Any) -> FakeProcess:
        raise FileNotFoundError("ffmpeg is unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unavailable)

    with pytest.raises(ProtocolError, match="could not start") as caught:
        await camera.snapshot("192.0.2.1", "12345678")

    assert isinstance(caught.value.__cause__, FileNotFoundError)


@pytest.mark.asyncio
async def test_snapshot_success_error_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess()

    async def create(*args: Any, **kwargs: Any) -> FakeProcess:
        assert args[0] == "ffmpeg"
        assert "-nostdin" in args
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    assert await camera.snapshot("192.0.2.1", "12345678") == b"jpeg"
    process.returncode = 1
    process.stdout = b""
    process.stderr = b"decoder error"
    with pytest.raises(ProtocolError, match="decoder error"):
        await camera.snapshot("192.0.2.1", "12345678")

    async def timeout(awaitable: Any, timeout_seconds: float) -> Any:
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout)
    with pytest.raises(ProtocolError, match="timed out"):
        await camera.snapshot("192.0.2.1", "12345678")
    assert process.killed


@pytest.mark.asyncio
async def test_simulated_gateway_snapshots_command_parameters() -> None:
    gateway = SimulatedGateway()
    parameters = {"nested": {"value": 1}}

    result = await gateway.command("print", "custom", parameters)
    parameters["nested"]["value"] = 2
    parameters["added"] = True

    expected = {"nested": {"value": 1}}
    assert gateway.commands[-1][2] == expected
    assert result.payload["parameters"] == expected


@pytest.mark.asyncio
async def test_simulated_gateway_and_pool(tmp_path: Path) -> None:
    gateway = SimulatedGateway(fail_commands={"bad"})
    assert (await gateway.status())["print"]["gcode_state"] == "IDLE"
    assert (await gateway.command("print", "project_file")).result == "success"
    assert (await gateway.status())["print"]["gcode_state"] == "RUNNING"
    assert (await gateway.command("print", "pause")).result == "success"
    assert (await gateway.command("print", "resume")).result == "success"
    assert (await gateway.command("print", "stop")).result == "success"
    assert (await gateway.command("print", "bad")).result == "failed"
    source = tmp_path / "x"
    source.write_bytes(b"data")
    await gateway.upload("x", source)
    assert await gateway.files() == ["x"]
    await gateway.delete("x")
    with pytest.raises(ProtocolError, match="does not exist"):
        await gateway.delete("x")

    printer = Printer(
        id="printer",
        name="p",
        serial="SERIAL1",
        host="192.0.2.1",
        encrypted_access_code="not-used",
    )
    created: list[tuple[str, TrackingGateway]] = []

    class TrackingGateway(SimulatedGateway):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    def factory(record: Printer, access_code: str) -> TrackingGateway:
        assert record is printer
        gateway = TrackingGateway()
        created.append((access_code, gateway))
        return gateway

    pool = GatewayPool(factory)
    first = await pool.get(printer, "code")
    assert first is await pool.get(printer, "code")
    assert len(created) == 1
    rotated = await pool.get(printer, "rotated-code")
    assert rotated is not first
    assert [access_code for access_code, _gateway in created] == ["code", "rotated-code"]
    assert created[0][1].close_calls == 1
    await pool.close()
    assert pool._gateways == {}
    assert pool._credential_digests == {}
    assert created[1][1].close_calls == 1
