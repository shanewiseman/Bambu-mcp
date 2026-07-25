"""Implicit FTPS operations restricted to printer artifact basenames."""

from __future__ import annotations

# The adapter instantiates only FTP_TLS and enforces the configured CA context.
import ftplib  # nosec B402
import io
import socket
from pathlib import Path
from typing import BinaryIO

from bambu_mcp.errors import ProtocolError, ValidationError
from bambu_mcp.protocol.mqtt import verified_tls_context


def stream_position(source: BinaryIO) -> int | None:
    try:
        return source.tell()
    except (AttributeError, OSError, io.UnsupportedOperation):
        return None


def remote_filename(name: str) -> str:
    if (
        not name
        or name != Path(name).name
        or any(char in name for char in ("\x00", "/", "\\"))
        or name in {".", ".."}
    ):
        raise ValidationError("printer filename must be a plain basename")
    return name


class ImplicitFTPTLS(ftplib.FTP_TLS):
    """FTP_TLS variant that wraps the control socket immediately on port 990."""

    def connect(
        self,
        host: str = "",
        port: int = 0,
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> str:
        self.host = host
        self.port = port or 990
        effective_timeout = self.timeout if timeout is None else timeout
        self.source_address = source_address
        self.sock = socket.create_connection(
            (self.host, self.port),
            effective_timeout,
            source_address=self.source_address,
        )
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


class FTPSClient:
    def __init__(self, host: str, access_code: str, ca_file: Path, timeout: float = 30) -> None:
        self.host = host
        self.access_code = access_code
        self.ca_file = ca_file
        self.timeout = timeout

    def _connect(self) -> ImplicitFTPTLS:
        context = verified_tls_context(self.ca_file)
        client = ImplicitFTPTLS(context=context, timeout=self.timeout)
        try:
            client.connect(self.host, 990)
            client.login("bblp", self.access_code)
            client.prot_p()
            return client
        except (OSError, ftplib.Error) as exc:
            client.close()
            raise ProtocolError("implicit FTPS connection failed") from exc

    @staticmethod
    def _disconnect(client: ImplicitFTPTLS) -> None:
        try:
            client.quit()
        except (OSError, ftplib.Error):
            client.close()

    def upload(self, name: str, source: BinaryIO) -> None:
        filename = remote_filename(name)
        client = self._connect()
        try:
            start = stream_position(source)
            client.storbinary(f"STOR {filename}", source)
            size = client.size(filename)
            end = stream_position(source)
            expected = None if start is None or end is None else end - start
            if size is not None and expected is not None and size != expected:
                raise ProtocolError("FTPS upload size verification failed")
        except (OSError, ftplib.Error) as exc:
            raise ProtocolError("FTPS upload failed") from exc
        finally:
            self._disconnect(client)

    def list_files(self) -> list[str]:
        client = self._connect()
        try:
            return sorted(client.nlst())
        except (OSError, ftplib.Error) as exc:
            raise ProtocolError("FTPS listing failed") from exc
        finally:
            self._disconnect(client)

    def delete(self, name: str) -> None:
        filename = remote_filename(name)
        client = self._connect()
        try:
            client.delete(filename)
        except (OSError, ftplib.Error) as exc:
            raise ProtocolError("FTPS delete failed") from exc
        finally:
            self._disconnect(client)
