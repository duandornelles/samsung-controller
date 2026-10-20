"""Fakes reutilizáveis dos canais (nunca abrem socket)."""

import asyncio
import json
from typing import Any

from websockets.protocol import State


class FakeRest:
    """Cliente REST falso: devolve `response` ou levanta `error`."""

    def __init__(self, response: dict[str, Any] | None = None, error: BaseException | None = None):
        self.response = response if response is not None else {"device": {}}
        self.error = error
        self.calls = 0

    async def rest_device_info(self) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


class FakeRestFactory:
    def __init__(self, rest: FakeRest):
        self.rest = rest
        self.hosts: list[str] = []

    def __call__(self, host: str, timeout: float) -> FakeRest:
        self.hosts.append(host)
        return self.rest


class FakeRemote:
    """WebSocket falso no formato de SamsungTVWSAsyncRemote."""

    def __init__(self, factory: "FakeWsFactory", host: str, token: str | None):
        self.factory = factory
        self.host = host
        self.token = token
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        f = self.factory
        f.open_calls += 1
        f.open_started.set()
        if f.open_delay:
            await asyncio.sleep(f.open_delay)
        if f.block_open:
            await asyncio.Event().wait()  # "Permitir" nunca respondido
        if f.open_errors:
            raise f.open_errors.pop(0)
        if self.token is None and f.issue_token is not None:
            self.token = f.issue_token
        self.opened = True

    async def send_commands(self, commands: list[Any], key_press_delay: float | None = None) -> None:
        if self.factory.send_errors:
            raise self.factory.send_errors.pop(0)
        for cmd in commands:
            self.factory.sent.append(cmd.as_dict())

    def is_alive(self) -> bool:
        return self.opened and not self.closed

    async def close(self) -> None:
        self.closed = True


class FakeWsFactory:
    def __init__(self, issue_token: str | None = None):
        self.issue_token = issue_token
        self.block_open = False
        self.open_delay = 0.0
        self.open_errors: list[BaseException] = []
        self.send_errors: list[BaseException] = []
        self.open_started = asyncio.Event()
        self.open_calls = 0
        self.created: list[FakeRemote] = []
        self.sent: list[dict[str, Any]] = []

    def __call__(self, host: str, token: str | None, timeout: float) -> FakeRemote:
        remote = FakeRemote(self, host, token)
        self.created.append(remote)
        return remote

    def remote_cmds(self) -> list[tuple[str, str]]:
        """(Cmd, DataOfCmd) das teclas enviadas."""
        return [
            (c["params"]["Cmd"], c["params"]["DataOfCmd"])
            for c in self.sent
            if c["method"] == "ms.remote.control"
        ]


class FakeConnection:
    """``websockets`` ClientConnection falso: aberto pelo connect(), ainda não
    atribuído a ``remote.connection`` enquanto o laço de ``ms.channel.connect`` roda.
    Sem mensagens na fila, ``recv()`` bloqueia (TV mostrando "Permitir")."""

    def __init__(self, messages: list[dict[str, Any]] | None = None):
        self.messages = list(messages or [])
        self.closed = False
        self.state = State.OPEN
        self.sent: list[str] = []

    async def recv(self) -> str:
        if not self.messages:
            await asyncio.Event().wait()
        return json.dumps(self.messages.pop(0))

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True
        self.state = State.CLOSED


class FakeConnect:
    """Substitui ``websockets.asyncio.client.connect`` no módulo do canal."""

    def __init__(self, *conns: FakeConnection):
        self.conns = list(conns)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, url: str, **kwargs: Any) -> FakeConnection:
        self.calls.append((url, kwargs))
        return self.conns.pop(0)
