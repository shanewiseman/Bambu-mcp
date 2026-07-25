"""MQTT QoS-1 sequencing, acknowledgement correlation, and reconnect state."""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, Protocol

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from bambu_mcp.errors import ProtocolError, ValidationError
from bambu_mcp.schemas import CommandResult
from bambu_mcp.state import deep_merge


class PublishTransport(Protocol):
    async def publish(self, topic: str, payload: bytes, qos: int) -> None: ...


class SequenceGenerator:
    def __init__(self, initial: int = 0) -> None:
        self._value = initial
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            self._value += 1
            return str(self._value)


class AckTracker:
    """Map sequence IDs to futures and tolerate duplicate QoS deliveries."""

    def __init__(self, max_completed: int = 1_024) -> None:
        self._pending: dict[str, asyncio.Future[CommandResult]] = {}
        self._completed: OrderedDict[str, CommandResult] = OrderedDict()
        self._max_completed = max_completed

    def register(self, sequence_id: str) -> asyncio.Future[CommandResult]:
        if sequence_id in self._pending or sequence_id in self._completed:
            raise ProtocolError(f"sequence ID was reused: {sequence_id}")
        future = asyncio.get_running_loop().create_future()
        self._pending[sequence_id] = future
        return future

    def resolve(self, result: CommandResult) -> bool:
        if result.sequence_id in self._completed:
            return False
        future = self._pending.pop(result.sequence_id, None)
        if future is None:
            return False
        self._remember(result)
        if not future.done():
            future.set_result(result)
        return True

    def fail_all(self, reason: str) -> None:
        for sequence_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(ProtocolError(reason))
            self._pending.pop(sequence_id, None)

    def _remember(self, result: CommandResult) -> None:
        self._completed[result.sequence_id] = result
        self._completed.move_to_end(result.sequence_id)
        while len(self._completed) > self._max_completed:
            self._completed.popitem(last=False)


class MQTTCommandClient:
    """Protocol-neutral command client using only the printer request/report topics."""

    def __init__(
        self,
        serial: str,
        transport: PublishTransport,
        *,
        ack_timeout: float,
        state_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.serial = serial
        self.transport = transport
        self.ack_timeout = ack_timeout
        self.sequence = SequenceGenerator()
        self.acks = AckTracker()
        self.state: dict[str, Any] = {}
        self.state_callback = state_callback

    @property
    def request_topic(self) -> str:
        return f"device/{self.serial}/request"

    @property
    def report_topic(self) -> str:
        return f"device/{self.serial}/report"

    async def command(
        self,
        family: str,
        command: str,
        parameters: dict[str, Any] | None = None,
    ) -> CommandResult:
        if not family.isidentifier() or not command.replace("_", "").isalnum():
            raise ValidationError("invalid protocol family or command")
        sequence_id = self.sequence.next()
        payload = {
            family: {
                "sequence_id": sequence_id,
                "command": command,
                **(parameters or {}),
            }
        }
        future = self.acks.register(sequence_id)
        try:
            await self.transport.publish(
                self.request_topic,
                json.dumps(payload, separators=(",", ":")).encode(),
                qos=1,
            )
            return await asyncio.wait_for(future, timeout=self.ack_timeout)
        except TimeoutError as exc:
            self.acks._pending.pop(sequence_id, None)
            raise ProtocolError(f"printer did not acknowledge {family}.{command}") from exc
        except Exception:
            self.acks._pending.pop(sequence_id, None)
            raise

    async def receive(self, topic: str, payload: bytes) -> None:
        if topic != self.report_topic:
            raise ProtocolError("received a message on an unexpected MQTT topic")
        try:
            report = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("printer returned invalid JSON") from exc
        if not isinstance(report, dict):
            raise ProtocolError("printer report must be a JSON object")

        self.state = deep_merge(self.state, report)
        for family_payload in report.values():
            if not isinstance(family_payload, dict):
                continue
            sequence_id = family_payload.get("sequence_id")
            command = family_payload.get("command")
            result = family_payload.get("result")
            if sequence_id is None or command is None or result is None:
                continue
            normalized = str(result).lower()
            self.acks.resolve(
                CommandResult(
                    sequence_id=str(sequence_id),
                    command=str(command),
                    result="success" if normalized == "success" else "failed",
                    reason=str(family_payload.get("reason", "")),
                    payload=family_payload,
                )
            )
        if self.state_callback:
            await self.state_callback(self.state)

    async def request_full_state(self) -> CommandResult:
        return await self.command("pushing", "pushall", {"version": 1, "push_target": 1})

    def disconnected(self) -> None:
        self.acks.fail_all("MQTT connection was lost before acknowledgement")


def verified_tls_context(ca_file: Path) -> ssl.SSLContext:
    """Build a Bambu-CA-verifying context without a blanket insecure mode.

    Current LAN certificates do not identify printer IP addresses, so hostname
    matching cannot be performed. Chain verification against the pinned CA
    remains mandatory.
    """
    context = ssl.create_default_context(cafile=str(ca_file))
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = False
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class PahoTransport:
    """Paho adapter; callbacks bridge into the owning asyncio event loop."""

    def __init__(
        self,
        *,
        host: str,
        serial: str,
        access_code: str,
        ca_file: Path,
        receiver: Callable[[str, bytes], Coroutine[Any, Any, None]],
    ) -> None:
        self.host = host
        self.serial = serial
        self.receiver = receiver
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2)
        self.client.username_pw_set("bblp", access_code)
        self.client.tls_set_context(verified_tls_context(ca_file))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    async def connect(self) -> None:
        self.loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.client.connect, self.host, 8883, 60)
        self.client.loop_start()

    async def close(self) -> None:
        self.client.loop_stop()
        await asyncio.to_thread(self.client.disconnect)

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        if topic != f"device/{self.serial}/request":
            raise ProtocolError("publishing outside the printer request topic is forbidden")
        result = self.client.publish(topic, payload, qos=qos)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ProtocolError(f"MQTT publish failed with code {result.rc}")
        await asyncio.to_thread(result.wait_for_publish, 10)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del userdata, flags, properties
        if reason_code.is_failure:
            return
        client.subscribe(f"device/{self.serial}/report", qos=1)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        del client, userdata
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self.receiver(message.topic, bytes(message.payload)),
                self.loop,
            )
