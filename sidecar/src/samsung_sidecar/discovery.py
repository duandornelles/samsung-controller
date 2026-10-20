"""Descoberta da TV Samsung na rede local: SSDP + confirmação pelo REST :8001."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .channels.local import LocalChannel, RestFactory, default_rest_factory
from .errors import TVNotFound, TVUnreachable

SSDP_ADDR = ("239.255.255.250", 1900)
SEARCH_TARGET = "urn:samsung.com:device:RemoteControlReceiver:1"


@dataclass(frozen=True)
class TVCandidate:
    host: str
    name: str


def msearch_message(timeout: float) -> bytes:
    mx = max(1, min(5, int(timeout)))
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {mx}\r\n"
        f"ST: {SEARCH_TARGET}\r\n"
        "\r\n"
    ).encode()


def parse_ssdp(data: bytes) -> dict[str, str] | None:
    """Cabeçalhos (chaves minúsculas) de uma resposta ``HTTP/1.1 200``; senão None."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.split("\r\n")
    if not lines[0].upper().startswith("HTTP/1.1 200"):
        return None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers


class _Collector(asyncio.DatagramProtocol):
    """Acumula (sem repetir) os IPs que responderam como RemoteControlReceiver."""

    def __init__(self) -> None:
        self.hosts: list[str] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        headers = parse_ssdp(data)
        if headers is None:
            return
        target = SEARCH_TARGET.lower()
        if target not in headers.get("st", "").lower() and target not in headers.get(
            "usn", ""
        ).lower():
            return
        if addr[0] not in self.hosts:
            self.hosts.append(addr[0])


async def ssdp_search(timeout: float = 3.0) -> list[str]:
    """Envia M-SEARCH multicast e coleta respostas por ``timeout`` segundos."""
    loop = asyncio.get_running_loop()
    try:
        transport, proto = await loop.create_datagram_endpoint(
            _Collector, local_addr=("0.0.0.0", 0), family=socket.AF_INET
        )
    except OSError:
        return []
    try:
        sock = transport.get_extra_info("socket")
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        msg = msearch_message(timeout)
        for _ in range(2):  # UDP: repete para tolerar perda
            transport.sendto(msg, SSDP_ADDR)
            await asyncio.sleep(0.1)
        await asyncio.sleep(max(0.0, timeout - 0.2))
    except OSError:
        pass
    finally:
        transport.close()
    return list(proto.hosts)


async def probe_rest(
    host: str, rest_factory: RestFactory = default_rest_factory
) -> TVCandidate | None:
    """Confirma a TV com ``GET http://<host>:8001/api/v2/``; inacessível → None."""
    channel = LocalChannel(host, None, lambda _token: None, rest_factory=rest_factory)
    try:
        device = await channel.device_info()
    except TVUnreachable:
        return None
    return TVCandidate(host, str(device.get("name") or host))


async def discover(
    timeout: float = 3.0,
    ssdp: Callable[[float], Awaitable[list[str]]] = ssdp_search,
    probe: Callable[[str], Awaitable[TVCandidate | None]] = probe_rest,
) -> list[TVCandidate]:
    hosts = list(dict.fromkeys(await ssdp(timeout)))
    results = await asyncio.gather(*(probe(h) for h in hosts), return_exceptions=True)
    return [r for r in results if isinstance(r, TVCandidate)]


def _norm_mac(mac: str) -> str:
    return mac.strip().lower().replace("-", ":")


async def find_tv(
    mac: str | None,
    get_mac: Callable[[str], Awaitable[str | None]],
    discover: Callable[[], Awaitable[list[TVCandidate]]] = discover,
) -> tuple[TVCandidate, str | None]:
    """Acha a TV pelo MAC (ou a primeira que responder se ``mac`` for None)."""
    wanted = _norm_mac(mac) if mac else None
    for cand in await discover():
        try:
            got = await get_mac(cand.host)
        except Exception:
            continue
        got = _norm_mac(got) if got else None
        if wanted is None or got == wanted:
            return cand, got
    raise TVNotFound("TV não encontrada na rede")
