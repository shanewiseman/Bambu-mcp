"""RTSPS snapshot capture using an argument-safe ffmpeg subprocess."""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import quote

from bambu_mcp.errors import ProtocolError, ValidationError


def camera_url(host: str, access_code: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValidationError("camera snapshots require a literal printer IP") from exc
    encoded_access_code = quote(access_code, safe="")
    url_host = f"[{address}]" if address.version == 6 else str(address)
    return f"rtsps://bblp:{encoded_access_code}@{url_host}:322/streaming/live/1"


async def snapshot(host: str, access_code: str, *, timeout_seconds: float = 15) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            camera_url(host, access_code),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ProtocolError("camera snapshot process could not start") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ProtocolError("camera snapshot timed out") from exc
    if process.returncode != 0 or not stdout:
        reason = stderr.decode(errors="replace")[-200:]
        raise ProtocolError(f"camera snapshot failed: {reason}")
    return stdout
