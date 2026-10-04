from __future__ import annotations

import socket
import struct
from typing import BinaryIO


class ScanUnavailable(RuntimeError):
    pass


class ClamAV:
    """Clamd INSTREAM: only an exact clean response allows activation."""

    def __init__(self, host: str, port: int, max_bytes: int) -> None:
        self.host, self.port, self.max_bytes = host, port, max_bytes

    def scan(self, source: BinaryIO) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=30) as connection:
                connection.settimeout(120)
                connection.sendall(b"zINSTREAM\0")
                source.seek(0)
                size = 0
                while chunk := source.read(65536):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ScanUnavailable("Scanner size limit")
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(b"\0\0\0\0")
                response = b""
                while not response.endswith(b"\0") and len(response) < 4096:
                    part = connection.recv(4096 - len(response))
                    if not part:
                        break
                    response += part
                if response == b"stream: OK\0":
                    return True
                if response.startswith(b"stream: ") and response.endswith(b" FOUND\0"):
                    return False
                raise ScanUnavailable("Scanner did not confirm a verdict")
        except OSError:
            raise ScanUnavailable("Scanner unavailable") from None
