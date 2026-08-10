from __future__ import annotations

import socket


class UdpSender:
    def __init__(self, host: str, port: int):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, line: str) -> None:
        self._sock.sendto((line + "\n").encode("utf-8"), self._addr)
