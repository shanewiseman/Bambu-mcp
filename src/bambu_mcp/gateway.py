"""Printer gateway abstraction and LAN/simulated implementations."""

from __future__ import annotations

import asyncio
import hmac
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from bambu_mcp.errors import ProtocolError
from bambu_mcp.models import Printer
from bambu_mcp.protocol.ftps import FTPSClient
from bambu_mcp.protocol.mqtt import MQTTCommandClient, PahoTransport
from bambu_mcp.schemas import CommandResult


class PrinterGateway(Protocol):
    async def status(self) -> dict[str, Any]: ...

    async def command(
        self,
        family: str,
        command: str,
        parameters: dict[str, Any] | None = None,
    ) -> CommandResult: ...

    async def upload(self, filename: str, source: Path) -> None: ...

    async def files(self) -> list[str]: ...

    async def delete(self, filename: str) -> None: ...

    async def close(self) -> None: ...


GatewayFactory = Callable[[Printer, str], PrinterGateway]


class SimulatedGateway:
    """Deterministic contract gateway; never makes a network connection."""

    def __init__(
        self,
        *,
        state: dict[str, Any] | None = None,
        fail_commands: set[str] | None = None,
    ) -> None:
        self.state = state or {
            "print": {
                "gcode_state": "IDLE",
                "hms": [],
                "ams": {"ams": []},
                "developer_mode": True,
            }
        }
        self.fail_commands = fail_commands or set()
        self.uploads: dict[str, bytes] = {}
        self.commands: list[tuple[str, str, dict[str, Any]]] = []
        self.sequence = 0

    async def status(self) -> dict[str, Any]:
        return self.state

    async def command(
        self,
        family: str,
        command: str,
        parameters: dict[str, Any] | None = None,
    ) -> CommandResult:
        self.sequence += 1
        params = parameters or {}
        self.commands.append((family, command, params))
        if command in self.fail_commands:
            return CommandResult(
                sequence_id=str(self.sequence),
                command=command,
                result="failed",
                reason="injected contract failure",
            )
        if command == "pause":
            self.state.setdefault("print", {})["gcode_state"] = "PAUSE"
        elif command == "resume":
            self.state.setdefault("print", {})["gcode_state"] = "RUNNING"
        elif command == "stop":
            self.state.setdefault("print", {})["gcode_state"] = "IDLE"
        elif command == "project_file":
            self.state.setdefault("print", {})["gcode_state"] = "RUNNING"
        return CommandResult(
            sequence_id=str(self.sequence),
            command=command,
            result="success",
            payload={"parameters": params},
        )

    async def upload(self, filename: str, source: Path) -> None:
        self.uploads[filename] = await asyncio.to_thread(source.read_bytes)

    async def files(self) -> list[str]:
        return sorted(self.uploads)

    async def delete(self, filename: str) -> None:
        if filename not in self.uploads:
            raise ProtocolError("simulated printer file does not exist")
        del self.uploads[filename]

    async def close(self) -> None:
        return None


class LanGateway:
    """MQTT + implicit FTPS gateway for a single printer record."""

    def __init__(
        self,
        *,
        host: str,
        serial: str,
        access_code: str,
        ca_file: Path,
        ack_timeout: float,
    ) -> None:
        self.ftps = FTPSClient(host, access_code, ca_file)
        self.transport = PahoTransport(
            host=host,
            serial=serial,
            access_code=access_code,
            ca_file=ca_file,
            receiver=self._receive,
        )
        self.mqtt = MQTTCommandClient(serial, self.transport, ack_timeout=ack_timeout)
        self.connected = False

    async def _receive(self, topic: str, payload: bytes) -> None:
        await self.mqtt.receive(topic, payload)

    async def _ensure_connected(self) -> None:
        if not self.connected:
            await self.transport.connect()
            self.connected = True

    async def status(self) -> dict[str, Any]:
        await self._ensure_connected()
        await self.mqtt.request_full_state()
        return self.mqtt.state

    async def command(
        self,
        family: str,
        command: str,
        parameters: dict[str, Any] | None = None,
    ) -> CommandResult:
        await self._ensure_connected()
        return await self.mqtt.command(family, command, parameters)

    async def upload(self, filename: str, source: Path) -> None:
        with source.open("rb") as stream:
            await asyncio.to_thread(self.ftps.upload, filename, stream)

    async def files(self) -> list[str]:
        return await asyncio.to_thread(self.ftps.list_files)

    async def delete(self, filename: str) -> None:
        await asyncio.to_thread(self.ftps.delete, filename)

    async def close(self) -> None:
        if self.connected:
            await self.transport.close()
            self.connected = False


class GatewayPool:
    """Lazily instantiate and reuse gateways without persisting plaintext secrets."""

    def __init__(self, factory: GatewayFactory) -> None:
        self.factory = factory
        self._gateways: dict[str, PrinterGateway] = {}
        self._credential_digests: dict[str, bytes] = {}
        self._credential_digest_key = secrets.token_bytes(32)
        self._lock = asyncio.Lock()

    async def get(self, printer: Printer, access_code: str) -> PrinterGateway:
        credential_digest = hmac.digest(
            self._credential_digest_key,
            access_code.encode(),
            "sha256",
        )
        async with self._lock:
            gateway = self._gateways.get(printer.id)
            previous_digest = self._credential_digests.get(printer.id)
            if gateway is not None:
                if previous_digest is not None and hmac.compare_digest(
                    previous_digest,
                    credential_digest,
                ):
                    return gateway
                await gateway.close()
                self._gateways.pop(printer.id)
                self._credential_digests.pop(printer.id, None)
            gateway = self.factory(printer, access_code)
            self._gateways[printer.id] = gateway
            self._credential_digests[printer.id] = credential_digest
            return gateway

    async def close(self) -> None:
        async with self._lock:
            try:
                await asyncio.gather(*(gateway.close() for gateway in self._gateways.values()))
            finally:
                self._gateways.clear()
                self._credential_digests.clear()
