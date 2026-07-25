from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any

import pytest

from bambu_mcp.errors import ProtocolError, ValidationError
from bambu_mcp.protocol.mqtt import (
    AckTracker,
    MQTTCommandClient,
    PahoTransport,
    SequenceGenerator,
    verified_tls_context,
)
from bambu_mcp.schemas import CommandResult


class FakeTransport:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, int]] = []
        self.client: MQTTCommandClient | None = None
        self.error: Exception | None = None
        self.result = "success"

    async def publish(self, topic: str, payload: bytes, qos: int) -> None:
        self.published.append((topic, payload, qos))
        if self.error:
            raise self.error
        body = json.loads(payload)
        family, command_payload = next(iter(body.items()))
        if self.client:
            await self.client.receive(
                self.client.report_topic,
                json.dumps(
                    {
                        family: {
                            **command_payload,
                            "result": self.result.upper(),
                            "reason": "injected" if self.result != "success" else "",
                        }
                    }
                ).encode(),
            )


def test_sequence_generator() -> None:
    sequence = SequenceGenerator(40)
    assert sequence.next() == "41"
    assert sequence.next() == "42"


@pytest.mark.asyncio
async def test_ack_tracker_resolution_duplicate_and_failure() -> None:
    tracker = AckTracker(max_completed=1)
    future = tracker.register("1")
    with pytest.raises(ProtocolError, match="reused"):
        tracker.register("1")
    result = CommandResult(sequence_id="1", command="pause", result="success")
    assert tracker.resolve(result)
    assert await future == result
    assert not tracker.resolve(result)
    second = tracker.register("2")
    assert tracker.resolve(CommandResult(sequence_id="2", command="resume", result="success"))
    await second
    assert not tracker.resolve(result)
    pending = tracker.register("3")
    tracker.fail_all("lost")
    with pytest.raises(ProtocolError, match="lost"):
        await pending


@pytest.mark.asyncio
async def test_mqtt_command_success_failure_and_payload() -> None:
    transport = FakeTransport()
    callback_states: list[dict[str, Any]] = []

    async def callback(state: dict[str, Any]) -> None:
        callback_states.append(state)

    client = MQTTCommandClient("SERIAL", transport, ack_timeout=0.1, state_callback=callback)
    transport.client = client
    result = await client.command("print", "pause", {"param": ""})
    assert result.result == "success"
    topic, payload, qos = transport.published[0]
    assert topic == "device/SERIAL/request"
    assert qos == 1
    assert json.loads(payload)["print"]["sequence_id"] == "1"
    assert callback_states
    transport.result = "failed"
    failed = await client.command("print", "resume")
    assert failed.result == "failed"
    assert failed.reason == "injected"
    assert (await client.request_full_state()).command == "pushall"


@pytest.mark.asyncio
async def test_mqtt_command_timeout_publish_error_and_validation() -> None:
    transport = FakeTransport()
    client = MQTTCommandClient("SERIAL", transport, ack_timeout=0.001)
    with pytest.raises(ProtocolError, match="acknowledge"):
        await client.command("print", "pause")
    transport.error = RuntimeError("publish failed")
    with pytest.raises(RuntimeError, match="publish failed"):
        await client.command("print", "pause")
    with pytest.raises(ValidationError, match="family"):
        await client.command("bad-family", "pause")


@pytest.mark.asyncio
async def test_receive_validation_sparse_state_and_stale_ack() -> None:
    transport = FakeTransport()
    client = MQTTCommandClient("SERIAL", transport, ack_timeout=0.1)
    with pytest.raises(ProtocolError, match="unexpected"):
        await client.receive("other", b"{}")
    with pytest.raises(ProtocolError, match="invalid JSON"):
        await client.receive(client.report_topic, b"{")
    with pytest.raises(ProtocolError, match="JSON object"):
        await client.receive(client.report_topic, b"[]")
    await client.receive(client.report_topic, b'{"print":{"temp":20,"ams":{"id":1}}}')
    await client.receive(client.report_topic, b'{"print":{"temp":21}}')
    assert client.state["print"] == {"temp": 21, "ams": {"id": 1}}
    await client.receive(
        client.report_topic,
        b'{"print":{"sequence_id":"404","command":"pause","result":"success"}}',
    )
    client.disconnected()


def test_verified_tls_context_uses_ca() -> None:
    context = verified_tls_context(Path("certs/bambu-lab-ca.pem"))
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    with pytest.raises(FileNotFoundError):
        verified_tls_context(Path("missing-ca.pem"))


@pytest.mark.asyncio
async def test_paho_transport_topic_and_publish_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receiver(topic: str, payload: bytes) -> None:
        del topic, payload

    transport = PahoTransport(
        host="192.0.2.10",
        serial="SERIAL",
        access_code="12345678",
        ca_file=Path("certs/bambu-lab-ca.pem"),
        receiver=receiver,
    )
    with pytest.raises(ProtocolError, match="outside"):
        await transport.publish("arbitrary/topic", b"{}", 1)

    class Info:
        rc = 0

        def wait_for_publish(self, timeout: float) -> bool:
            assert timeout == 10
            return True

    monkeypatch.setattr(transport.client, "publish", lambda *args, **kwargs: Info())
    await transport.publish("device/SERIAL/request", b"{}", 1)

    class BadInfo(Info):
        rc = 4

    monkeypatch.setattr(transport.client, "publish", lambda *args, **kwargs: BadInfo())
    with pytest.raises(ProtocolError, match="code 4"):
        await transport.publish("device/SERIAL/request", b"{}", 1)
