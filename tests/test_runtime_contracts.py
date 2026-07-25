from __future__ import annotations

import asyncio
import io
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bambu_mcp import cli
from bambu_mcp import gateway as gateway_module
from bambu_mcp.errors import ProtocolError
from bambu_mcp.gateway import LanGateway
from bambu_mcp.protocol import ftps
from bambu_mcp.protocol.ftps import FTPSClient, ImplicitFTPTLS
from bambu_mcp.schemas import CommandResult


def test_implicit_ftps_wraps_control_socket_before_welcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RawSocket:
        family = 2

    class WrappedSocket:
        def makefile(self, mode: str, *, encoding: str) -> io.StringIO:
            assert (mode, encoding) == ("r", "utf-8")
            return io.StringIO("")

    raw = RawSocket()
    wrapped = WrappedSocket()
    connection: dict[str, Any] = {}

    def create_connection(
        address: tuple[str, int],
        timeout: float,
        *,
        source_address: tuple[str, int] | None,
    ) -> RawSocket:
        connection.update(
            address=address,
            timeout=timeout,
            source_address=source_address,
        )
        return raw

    class TLSContext:
        def wrap_socket(self, sock: RawSocket) -> WrappedSocket:
            assert sock is raw
            return wrapped

    monkeypatch.setattr(ftps.socket, "create_connection", create_connection)
    client = object.__new__(ImplicitFTPTLS)
    client.timeout = 12
    client.context = TLSContext()
    client.encoding = "utf-8"
    monkeypatch.setattr(client, "getresp", lambda: "220 ready")

    assert client.connect("192.0.2.10", source_address=("192.0.2.20", 0)) == "220 ready"
    assert connection == {
        "address": ("192.0.2.10", 990),
        "timeout": 12,
        "source_address": ("192.0.2.20", 0),
    }
    assert client.sock is wrapped
    assert client.af == 2


@pytest.mark.parametrize("failure_stage", ["wrap", "makefile", "greeting"])
def test_implicit_ftps_closes_partial_socket_on_setup_failure(
    monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    class RawSocket:
        family = 2

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class PartialFile:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    raw = RawSocket()
    partial_file = PartialFile()

    class WrappedSocket:
        def __init__(self) -> None:
            self.closed = False

        def makefile(self, mode: str, *, encoding: str) -> PartialFile:
            assert (mode, encoding) == ("r", "utf-8")
            if failure_stage == "makefile":
                raise OSError("makefile failed")
            return partial_file

        def close(self) -> None:
            self.closed = True
            raw.close()

    wrapped = WrappedSocket()

    class TLSContext:
        def wrap_socket(self, sock: RawSocket) -> WrappedSocket:
            assert sock is raw
            if failure_stage == "wrap":
                raise OSError("wrap failed")
            return wrapped

    monkeypatch.setattr(ftps.socket, "create_connection", lambda *args, **kwargs: raw)
    client = object.__new__(ImplicitFTPTLS)
    client.timeout = 12
    client.context = TLSContext()
    client.encoding = "utf-8"
    client.file = None
    client.sock = None
    client.welcome = None

    def getresp() -> str:
        if failure_stage == "greeting":
            raise ftps.ftplib.error_temp("bad greeting")
        return "220 ready"

    monkeypatch.setattr(client, "getresp", getresp)
    with pytest.raises((OSError, ftps.ftplib.Error)):
        client.connect("192.0.2.10")

    assert raw.closed
    assert wrapped.closed is (failure_stage != "wrap")
    assert partial_file.closed is (failure_stage == "greeting")
    assert client.sock is None
    assert client.file is None
    assert client.welcome is None


def test_ftps_connection_authenticates_and_closes_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_context = object()
    created: list[FakeImplicit] = []

    class FakeImplicit:
        fail = False

        def __init__(self, *, context: object, timeout: float) -> None:
            assert context is sentinel_context
            assert timeout == 7
            self.calls: list[tuple[Any, ...]] = []
            self.closed = False
            created.append(self)

        def connect(self, host: str, port: int) -> None:
            self.calls.append(("connect", host, port))
            if self.fail:
                raise OSError("offline")

        def login(self, user: str, password: str) -> None:
            self.calls.append(("login", user, password))

        def prot_p(self) -> None:
            self.calls.append(("prot_p",))

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(ftps, "verified_tls_context", lambda path: sentinel_context)
    monkeypatch.setattr(ftps, "ImplicitFTPTLS", FakeImplicit)
    client = FTPSClient("192.0.2.10", "12345678", Path("ca.pem"), timeout=7)

    connected = client._connect()
    assert connected is created[0]
    assert created[0].calls == [
        ("connect", "192.0.2.10", 990),
        ("login", "bblp", "12345678"),
        ("prot_p",),
    ]

    FakeImplicit.fail = True
    with pytest.raises(ProtocolError, match="connection failed"):
        client._connect()
    assert created[-1].closed


@pytest.mark.asyncio
async def test_lan_gateway_connects_once_and_delegates_protocols(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFTPS:
        def __init__(self, host: str, access_code: str, ca_file: Path) -> None:
            assert (host, access_code, ca_file) == (
                "192.0.2.10",
                "12345678",
                tmp_path / "ca.pem",
            )
            self.uploads: dict[str, bytes] = {}
            self.deleted: list[str] = []

        def upload(self, filename: str, stream: Any) -> None:
            self.uploads[filename] = stream.read()

        def list_files(self) -> list[str]:
            return sorted(self.uploads)

        def delete(self, filename: str) -> None:
            self.deleted.append(filename)

    class FakeTransport:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["host"] == "192.0.2.10"
            assert kwargs["serial"] == "SERIAL1"
            self.receiver = kwargs["receiver"]
            self.disconnect_callback = kwargs["disconnect_callback"]
            self.connect_count = 0
            self.close_count = 0
            self.connect_started = asyncio.Event()
            self.release_connect = asyncio.Event()

        async def connect(self) -> None:
            self.connect_count += 1
            self.connect_started.set()
            await self.release_connect.wait()

        async def close(self) -> None:
            self.close_count += 1

    class FakeMQTT:
        def __init__(
            self,
            serial: str,
            transport: FakeTransport,
            *,
            ack_timeout: float,
        ) -> None:
            assert (serial, ack_timeout) == ("SERIAL1", 3)
            self.transport = transport
            self.state = {"print": {"gcode_state": "IDLE"}}
            self.received: list[tuple[str, bytes]] = []
            self.state_requests = 0
            self.disconnect_count = 0

        async def receive(self, topic: str, payload: bytes) -> None:
            self.received.append((topic, payload))

        async def request_full_state(self) -> None:
            self.state_requests += 1

        async def command(
            self,
            family: str,
            command: str,
            parameters: dict[str, Any] | None,
        ) -> CommandResult:
            assert (family, command, parameters) == ("print", "pause", {"reason": "test"})
            return CommandResult(sequence_id="1", command=command, result="success")

        def disconnected(self) -> None:
            self.disconnect_count += 1

    monkeypatch.setattr(gateway_module, "FTPSClient", FakeFTPS)
    monkeypatch.setattr(gateway_module, "PahoTransport", FakeTransport)
    monkeypatch.setattr(gateway_module, "MQTTCommandClient", FakeMQTT)
    gateway = LanGateway(
        host="192.0.2.10",
        serial="SERIAL1",
        access_code="12345678",
        ca_file=tmp_path / "ca.pem",
        ack_timeout=3,
    )

    await gateway._receive("device/SERIAL1/report", b"{}")
    assert gateway.mqtt.received == [("device/SERIAL1/report", b"{}")]

    first_status = asyncio.create_task(gateway.status())
    await gateway.transport.connect_started.wait()
    second_status = asyncio.create_task(gateway.status())
    await asyncio.sleep(0)
    assert gateway.transport.connect_count == 1
    gateway.transport.release_connect.set()
    statuses = await asyncio.gather(first_status, second_status)
    assert all(state["print"]["gcode_state"] == "IDLE" for state in statuses)
    assert gateway.mqtt.state_requests == 2

    assert (await gateway.command("print", "pause", {"reason": "test"})).result == "success"
    assert gateway.transport.connect_count == 1

    gateway.transport.disconnect_callback()
    assert gateway.connected is False
    assert gateway.mqtt.disconnect_count == 1
    await gateway.status()
    assert gateway.transport.connect_count == 2

    source = tmp_path / "plate.gcode.3mf"
    source.write_bytes(b"archive")
    await gateway.upload(source.name, source)
    assert await gateway.files() == [source.name]
    await gateway.delete(source.name)
    assert gateway.ftps.deleted == [source.name]

    await gateway.close()
    await gateway.close()
    assert gateway.transport.close_count == 1
    assert gateway.connected is False


def test_cli_runtime_commands_and_module_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_instances: list[Any] = []

    class FakeDatabase:
        def __init__(self, database_url: str) -> None:
            assert database_url == "sqlite:///cli.db"
            self.upgrade_calls = 0
            self.dispose_calls = 0
            self.engine = SimpleNamespace(dispose=self.dispose)
            database_instances.append(self)

        def upgrade_schema(self) -> None:
            self.upgrade_calls += 1

        def dispose(self) -> None:
            self.dispose_calls += 1

    container = SimpleNamespace(database=SimpleNamespace())
    prepared: list[bool] = []
    settings = SimpleNamespace(
        bind_host="127.0.0.1",
        bind_port=8123,
        log_level="WARNING",
        database_url="sqlite:///cli.db",
        prepare_directories=lambda: prepared.append(True),
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "Database", FakeDatabase)
    build_calls: list[Any] = []

    def fake_build_container(value: Any) -> Any:
        build_calls.append(value)
        return container

    monkeypatch.setattr(cli, "build_container", fake_build_container)

    monkeypatch.setattr("sys.argv", ["bambu-mcp", "init-db"])
    assert cli.main() is None
    assert prepared == [True]
    assert len(database_instances) == 1
    database = database_instances[0]
    assert (database.upgrade_calls, database.dispose_calls) == (1, 1)
    assert build_calls == []

    transports: list[str] = []
    mcp = SimpleNamespace(run=lambda *, transport: transports.append(transport))
    monkeypatch.setattr(cli, "create_mcp", lambda value: mcp)
    monkeypatch.setattr("sys.argv", ["bambu-mcp", "stdio"])
    assert cli.main() is None
    assert transports == ["stdio"]
    assert build_calls == [settings]

    app = object()
    uvicorn_call: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_app", lambda value: app)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda value, **kwargs: uvicorn_call.update(app=value, **kwargs),
    )
    monkeypatch.setattr("sys.argv", ["bambu-mcp", "http"])
    assert cli.main() is None
    assert uvicorn_call == {
        "app": app,
        "host": "127.0.0.1",
        "port": 8123,
        "log_level": "warning",
    }
    assert build_calls == [settings, settings]

    entrypoint_calls: list[bool] = []
    monkeypatch.setattr(cli, "main", lambda: entrypoint_calls.append(True))
    runpy.run_module("bambu_mcp.__main__", run_name="__main__")
    assert entrypoint_calls == [True]
