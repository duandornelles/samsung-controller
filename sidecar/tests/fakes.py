"""Fakes reutilizáveis dos canais (nunca abrem socket)."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from websockets.protocol import State

from samsung_sidecar.config import Config
from samsung_sidecar.discovery import TVCandidate
from samsung_sidecar.service import TVService


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


MAC = "aa:bb:cc:dd:ee:ff"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


class FakeLocal:
    def __init__(self, host, token, on_token):
        self.host = host
        self.token = token
        self.on_token = on_token
        self.powers: list[str | None] = ["on"]  # o último se repete
        self.calls: list[tuple] = []
        self.connected = False
        self.pairing_pending = False
        self.mac_value: str | None = MAC
        self.errors: list[BaseException] = []  # levantados por key/run_app/... em ordem
        self.connect_token: str | None = None
        self.closed = False
        self.power_hook = None

    async def power_state(self):
        self.calls.append(("power_state",))
        if self.power_hook is not None:
            await self.power_hook()
        return self.powers.pop(0) if len(self.powers) > 1 else self.powers[0]

    async def mac(self):
        return self.mac_value

    def _maybe_fail(self):
        if self.errors:
            raise self.errors.pop(0)

    async def key(self, k):
        self.calls.append(("key", k))
        self._maybe_fail()

    async def hold(self, k, s):
        self.calls.append(("hold", k, s))
        self._maybe_fail()

    async def run_app(self, app_id):
        self.calls.append(("run_app", app_id))
        self._maybe_fail()

    async def open_browser(self, url):
        self.calls.append(("open_browser", url))
        self._maybe_fail()

    async def reset_token(self):
        self.calls.append(("reset_token",))
        self.token = None
        self.connected = False

    async def connect(self):
        self.calls.append(("connect",))
        self._maybe_fail()
        if self.token is None and self.connect_token:
            self.token = self.connect_token
            self.on_token(self.token)
        self.connected = True

    async def set_host(self, host):
        self.calls.append(("set_host", host))
        self.host = host

    async def close(self):
        self.closed = True


class FakeST:
    def __init__(self, token, device_id):
        self.token = token
        self.device_id = device_id
        self.sources = ["HDMI1", "HDMI2", "digitalTv"]
        self.inputs_seq: list[str | None] = ["HDMI1"]  # inputSource lido; o último se repete
        self.modes = ["Dynamic", "Standard", "Movie", "FILMMAKER MODE", "Vivid"]
        self.mode_seq: list[str | None] = ["Standard"]
        self.bl: int | None = 40
        self.vol: dict | None = {"level": 12, "max": 100, "muted": False}
        self.commands: list[tuple] = []
        self.error: BaseException | None = None
        self.backlight_error: BaseException | None = None

    def _fail(self):
        if self.error is not None:
            raise self.error

    @staticmethod
    def _next(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    async def input_sources(self):
        self._fail()
        return list(self.sources), self._next(self.inputs_seq)

    async def set_input(self, source):
        self._fail()
        self.commands.append(("set_input", source))

    async def picture_modes(self):
        self._fail()
        return list(self.modes), self._next(self.mode_seq)

    async def set_picture_mode(self, mode):
        self._fail()
        self.commands.append(("set_picture_mode", mode))

    async def volume(self):
        self._fail()
        return self.vol

    async def backlight(self):
        self._fail()
        return self.bl

    async def set_backlight(self, v):
        self._fail()
        if self.backlight_error is not None:
            raise self.backlight_error
        self.commands.append(("set_backlight", v))


class Harness:
    def __init__(self, st=True, **cfg):
        defaults = {"tv_host": "10.0.0.5", "tv_mac": MAC, "ws_token": "tok"}
        if st:
            defaults |= {"st_token": "pat", "st_device_id": "dev"}
        defaults |= cfg
        self.config = Config(**defaults)
        self.locals: list[FakeLocal] = []
        self.sts: list[FakeST] = []
        self.wol_calls: list[str] = []
        self.sleeps: list[float] = []
        self.saved: list[Config] = []
        self.finder_calls: list[str | None] = []
        self.finder_result: tuple[TVCandidate, str | None] | BaseException = (
            TVCandidate("10.0.0.5", "[TV] Frame"),
            MAC,
        )
        self.st_setup = lambda st: None
        self.svc = TVService(
            self.config,
            self.local_factory,
            self.st_factory,
            wol=self.wol,
            finder=self.finder,
            save=lambda c: self.saved.append(Config(**vars(c))),
            sleep=self.sleep,
            now=lambda: NOW,
        )

    def local_factory(self, host, token, on_token):
        loc = FakeLocal(host, token, on_token)
        self.locals.append(loc)
        return loc

    def st_factory(self, token, device_id):
        st = FakeST(token, device_id)
        self.st_setup(st)
        self.sts.append(st)
        return st

    @property
    def local(self) -> FakeLocal:
        return self.locals[0]

    @property
    def st(self) -> FakeST:
        return self.sts[-1]

    async def wol(self, mac):
        self.wol_calls.append(mac)

    async def finder(self, mac, get_mac):
        self.finder_calls.append(mac)
        self.get_mac = get_mac
        if isinstance(self.finder_result, BaseException):
            raise self.finder_result
        return self.finder_result

    async def sleep(self, s):
        self.sleeps.append(s)
