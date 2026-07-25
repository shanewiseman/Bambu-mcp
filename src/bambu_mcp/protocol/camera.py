"""RTSPS snapshot capture using an argument-safe ffmpeg subprocess."""

from __future__ import annotations

import asyncio
import ipaddress

from bambu_mcp.errors import ProtocolError, ValidationError


def camera_url(host: str, access_code: str) -> str:
    try:
        ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValidationError("camera snapshots require a literal printer IP") from exc
    if any(char in access_code for char in "\r\n@:/"):
        raise ValidationError("access code contains URL-unsafe characters")
    return f"rtsps://bblp:{access_code}@{host}:322/streaming/live/1"


async def snapshot(host: str, access_code: str, *, timeout_seconds: float = 15) -> bytes:
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
