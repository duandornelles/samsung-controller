"""Wake-on-LAN."""

import asyncio
import re
import socket
from collections.abc import Awaitable, Callable

Sender = Callable[[bytes, tuple[str, int]], Awaitable[None]]

_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$")


def valid_mac(mac: str | None) -> bool:
    return bool(mac) and _MAC_RE.match(mac) is not None


def magic_packet(mac: str) -> bytes:
    if not _MAC_RE.match(mac):
        raise ValueError(f"MAC inválido: {mac!r}")
    raw = bytes.fromhex(re.sub(r"[:-]", "", mac))
    return b"\xff" * 6 + raw * 16


async def _udp_sender(packet: bytes, addr: tuple[str, int]) -> None:
    def _send() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, addr)

    await asyncio.to_thread(_send)


async def send_magic_packet(
    mac: str,
    broadcast: str = "255.255.255.255",
    ports: tuple[int, ...] = (9, 7),
    sender: Sender | None = None,
) -> None:
    packet = magic_packet(mac)
    send = sender or _udp_sender
    for port in ports:
        await send(packet, (broadcast, port))
