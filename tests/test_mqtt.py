from __future__ import annotations

import asyncio
import json
import logging
import ssl
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import paho.mqtt.client as mqtt
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
async def test_mqtt_command_timeout_publish_error_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport()
    client = MQTTCommandClient("SERIAL", transport, ack_timeout=0.001)
    registered: list[asyncio.Future[CommandResult]] = []
    register = client.acks.register

    def capture_future(sequence_id: str) -> asyncio.Future[CommandResult]:
        future = register(sequence_id)
        registered.append(future)
        return future

    monkeypatch.setattr(client.acks, "register", capture_future)
    for reserved in ("sequence_id", "command"):
        with pytest.raises(ValidationError, match="reserved MQTT envelope"):
            await client.command("print", "pause", {reserved: "tampered"})
    assert transport.published == []
    assert client.sequence.next() == "1"
    with pytest.raises(ProtocolError, match="acknowledge"):
        await client.command("print", "pause")
    assert registered[-1].cancelled()
    transport.error = RuntimeError("publish failed")
    with pytest.raises(RuntimeError, match="publish failed"):
        await client.command("print", "pause")
    assert registered[-1].cancelled()
    for family, command in (
        ("bad-family", "pause"),
        ("Print", "pause"),
        ("prínt", "pause"),
        ("print", "Pause"),
        ("print", "paúse"),
    ):
        with pytest.raises(ValidationError, match="family"):
            await client.command(family, command)


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
    for sequence_id, reported, expected in (
        ("405", "TIMEOUT", "timeout"),
        ("406", "rejected", "rejected"),
        ("407", "unknown", "failed"),
    ):
        pending = client.acks.register(sequence_id)
        await client.receive(
            client.report_topic,
            json.dumps(
                {
                    "print": {
                        "sequence_id": sequence_id,
                        "command": "pause",
                        "result": reported,
                    }
                }
            ).encode(),
        )
        assert (await pending).result == expected
    client.disconnected()


def test_paho_receiver_future_surfaces_failures(caplog: pytest.LogCaptureFixture) -> None:
    completed: Future[None] = Future()
    completed.set_result(None)
    PahoTransport._receiver_done(completed)
    assert not caplog.records

    failed: Future[None] = Future()
    failed.set_exception(ProtocolError("injected receiver failure"))
    with caplog.at_level(logging.ERROR, logger="bambu_mcp.protocol.mqtt"):
        PahoTransport._receiver_done(failed)
    assert "MQTT report receiver failed" in caplog.text
    assert "injected receiver failure" in caplog.text


def test_paho_on_message_observes_receiver_future(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receiver(topic: str, payload: bytes) -> None:
        del topic, payload

    transport = PahoTransport(
        host="192.0.2.10",
        serial="SERIAL",
        access_code="12345678",
        ca_file=Path("certs/bambu-lab-ca.pem"),
        receiver=receiver,
        disconnect_callback=lambda: None,
    )
    message = SimpleNamespace(topic="device/SERIAL/report", payload=b"{}")
    transport._on_message(transport.client, None, message)

    submitted: Future[None] = Future()
    submitted.set_result(None)
    observed: list[Future[None]] = []

    def submit(coroutine: Any, loop: Any) -> Future[None]:
        assert loop is transport.loop
        coroutine.close()
        return submitted

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)
    monkeypatch.setattr(transport, "_receiver_done", lambda future: observed.append(future))
    transport.loop = asyncio.new_event_loop()
    try:
        transport._on_message(transport.client, None, message)
    finally:
        transport.loop.close()
    assert observed == [submitted]


def make_paho_transport(*, connect_timeout: float = 0.05) -> PahoTransport:
    async def receiver(topic: str, payload: bytes) -> None:
        del topic, payload

    return PahoTransport(
        host="192.0.2.10",
        serial="SERIAL",
        access_code="12345678",
        ca_file=Path("certs/bambu-lab-ca.pem"),
        receiver=receiver,
        disconnect_callback=lambda: None,
        connect_timeout=connect_timeout,
    )


@pytest.mark.asyncio
async def test_paho_connect_waits_for_report_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = make_paho_transport()
    loop_started = asyncio.Event()
    subscriptions: list[tuple[str, int]] = []

    monkeypatch.setattr(
        transport.client,
        "connect",
        lambda host, port, keepalive: mqtt.MQTT_ERR_SUCCESS,
    )

    def subscribe(topic: str, qos: int) -> tuple[int, int]:
        subscriptions.append((topic, qos))
        return mqtt.MQTT_ERR_SUCCESS, 17

    def loop_start() -> int:
        loop_started.set()
        return mqtt.MQTT_ERR_SUCCESS

    monkeypatch.setattr(transport.client, "subscribe", subscribe)
    monkeypatch.setattr(transport.client, "loop_start", loop_start)
    connection = asyncio.create_task(transport.connect())
    await loop_started.wait()

    transport._on_connect(
        transport.client,
        None,
        SimpleNamespace(),
        SimpleNamespace(is_failure=False),
        None,
    )
    await asyncio.sleep(0)
    assert not connection.done()
    assert subscriptions == [("device/SERIAL/report", 1)]

    transport._on_subscribe(
        transport.client,
        None,
        17,
        [SimpleNamespace(is_failure=False)],
        None,
    )
    await connection
    assert transport._ready.is_set()


@pytest.mark.parametrize("failure_stage", ["connack", "subscribe"])
@pytest.mark.asyncio
async def test_paho_connect_rejects_handshake_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    transport = make_paho_transport()
    cleanup: list[str] = []
    monkeypatch.setattr(
        transport.client,
        "connect",
        lambda host, port, keepalive: mqtt.MQTT_ERR_SUCCESS,
    )
    monkeypatch.setattr(
        transport.client,
        "subscribe",
        lambda topic, qos: (mqtt.MQTT_ERR_SUCCESS, 23),
    )
    monkeypatch.setattr(transport.client, "disconnect", lambda: cleanup.append("disconnect"))
    monkeypatch.setattr(transport.client, "loop_stop", lambda: cleanup.append("loop_stop"))

    def loop_start() -> int:
        transport._on_connect(
            transport.client,
            None,
            SimpleNamespace(),
            SimpleNamespace(is_failure=failure_stage == "connack"),
            None,
        )
        if failure_stage == "subscribe":
            transport._on_subscribe(
                transport.client,
                None,
                23,
                [SimpleNamespace(is_failure=True)],
                None,
            )
        return mqtt.MQTT_ERR_SUCCESS

    monkeypatch.setattr(transport.client, "loop_start", loop_start)

    with pytest.raises(ProtocolError, match="rejected"):
        await transport.connect()

    assert cleanup == ["disconnect", "loop_stop"]
    assert not transport._ready.is_set()


@pytest.mark.asyncio
async def test_paho_connect_times_out_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = make_paho_transport(connect_timeout=0.001)
    cleanup: list[str] = []
    monkeypatch.setattr(
        transport.client,
        "connect",
        lambda host, port, keepalive: mqtt.MQTT_ERR_SUCCESS,
    )
    monkeypatch.setattr(transport.client, "loop_start", lambda: mqtt.MQTT_ERR_SUCCESS)
    monkeypatch.setattr(transport.client, "disconnect", lambda: cleanup.append("disconnect"))
    monkeypatch.setattr(transport.client, "loop_stop", lambda: cleanup.append("loop_stop"))

    with pytest.raises(ProtocolError, match="handshake timed out"):
        await transport.connect()

    assert cleanup == ["disconnect", "loop_stop"]


@pytest.mark.parametrize(
    ("connect_result", "loop_result", "message"),
    [
        (mqtt.MQTT_ERR_NO_CONN, mqtt.MQTT_ERR_SUCCESS, "connect failed"),
        (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_INVAL, "network loop failed"),
    ],
)
@pytest.mark.asyncio
async def test_paho_connect_rejects_immediate_errors(
    monkeypatch: pytest.MonkeyPatch,
    connect_result: int,
    loop_result: int,
    message: str,
) -> None:
    transport = make_paho_transport()
    cleanup: list[str] = []
    monkeypatch.setattr(
        transport.client,
        "connect",
        lambda host, port, keepalive: connect_result,
    )
    monkeypatch.setattr(transport.client, "loop_start", lambda: loop_result)
    monkeypatch.setattr(transport.client, "disconnect", lambda: cleanup.append("disconnect"))

    with pytest.raises(ProtocolError, match=message):
        await transport.connect()

    assert cleanup == ["disconnect"]


@pytest.mark.asyncio
async def test_paho_disconnect_fails_pending_ack_from_callback_thread() -> None:
    client: MQTTCommandClient

    async def receiver(topic: str, payload: bytes) -> None:
        del topic, payload

    transport = PahoTransport(
        host="192.0.2.10",
        serial="SERIAL",
        access_code="12345678",
        ca_file=Path("certs/bambu-lab-ca.pem"),
        receiver=receiver,
        disconnect_callback=lambda: client.disconnected(),
    )
    client = MQTTCommandClient("SERIAL", transport, ack_timeout=0.1)
    transport._ready.set()
    transport.loop = asyncio.get_running_loop()
    pending = client.acks.register("1")

    await asyncio.to_thread(
        transport._on_disconnect,
        transport.client,
        None,
        SimpleNamespace(),
        SimpleNamespace(),
        None,
    )
    await asyncio.sleep(0)
    assert not transport._ready.is_set()

    with pytest.raises(ProtocolError, match="connection was lost"):
        await pending


@pytest.mark.asyncio
async def test_paho_close_disconnects_before_stopping_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def receiver(topic: str, payload: bytes) -> None:
        del topic, payload

    transport = PahoTransport(
        host="192.0.2.10",
        serial="SERIAL",
        access_code="12345678",
        ca_file=Path("certs/bambu-lab-ca.pem"),
        receiver=receiver,
        disconnect_callback=lambda: None,
    )
    calls: list[str] = []

    def disconnect() -> None:
        calls.append("disconnect")

    def loop_stop() -> None:
        calls.append("loop_stop")

    monkeypatch.setattr(transport.client, "disconnect", disconnect)
    monkeypatch.setattr(transport.client, "loop_stop", loop_stop)
    transport._ready.set()
    await transport.close()
    assert calls == ["disconnect", "loop_stop"]
    assert not transport._ready.is_set()

    calls.clear()

    def failed_disconnect() -> None:
        calls.append("disconnect")
        raise OSError("disconnect failed")

    monkeypatch.setattr(transport.client, "disconnect", failed_disconnect)
    with pytest.raises(OSError, match="disconnect failed"):
        await transport.close()
    assert calls == ["disconnect", "loop_stop"]


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
        disconnect_callback=lambda: None,
    )
    with pytest.raises(ProtocolError, match="outside"):
        await transport.publish("arbitrary/topic", b"{}", 1)
    with pytest.raises(ProtocolError, match="not ready"):
        await transport.publish("device/SERIAL/request", b"{}", 1)
    transport._ready.set()

    class Info:
        rc = 0
        published = True

        def wait_for_publish(self, timeout: float) -> None:
            assert timeout == 10

        def is_published(self) -> bool:
            return self.published

    monkeypatch.setattr(transport.client, "publish", lambda *args, **kwargs: Info())
    await transport.publish("device/SERIAL/request", b"{}", 1)

    class PendingInfo(Info):
        published = False

    monkeypatch.setattr(transport.client, "publish", lambda *args, **kwargs: PendingInfo())
    with pytest.raises(ProtocolError, match="did not complete"):
        await transport.publish("device/SERIAL/request", b"{}", 1)

    class BadInfo(Info):
        rc = 4

    monkeypatch.setattr(transport.client, "publish", lambda *args, **kwargs: BadInfo())
    with pytest.raises(ProtocolError, match="code 4"):
        await transport.publish("device/SERIAL/request", b"{}", 1)
