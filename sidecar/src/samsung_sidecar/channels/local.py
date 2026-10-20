"""Canal local da TV Samsung: REST :8001 (info/energia) + WebSocket :8002 (teclas, apps).

O WebSocket usa ``samsungtvws`` (``SamsungTVWSAsyncRemote``) e é criado por uma
fábrica injetável, para que os testes nunca abram socket.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

import aiohttp
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.command import SamsungTVCommand
from samsungtvws.connection import SamsungTVWSBaseConnection
from samsungtvws import helper
from samsungtvws.event import (
    IGNORE_EVENTS_AT_STARTUP,
    MS_CHANNEL_CONNECT_EVENT,
    MS_CHANNEL_UNAUTHORIZED,
)
from samsungtvws.exceptions import ConnectionFailure, UnauthorizedError
from samsungtvws.remote import ChannelEmitCommand, SendRemoteKey
from websockets.asyncio.client import ClientConnection, connect

from samsung_sidecar.errors import AdbUnauthorized, TVUnreachable

CLIENT_NAME = "Samsung Controller"
REST_PORT = 8001
WS_PORT = 8002
BROWSER_APP_ID = "org.tizen.browser"

_UNREACHABLE_MSG = "TV inacessível (API local)"
_PAIRING_TIMEOUT_MSG = "Aceite o pedido de conexão na TV"
_DENIED_MSG = "Pedido de conexão recusado na TV"

# Nunca logar tokens: a lib loga o token em INFO (connection.py:95) e a URL com o
# token em DEBUG (async_connection.py:56).
logging.getLogger("samsungtvws").setLevel(logging.WARNING)


class RestClient(Protocol):
    async def rest_device_info(self) -> dict[str, Any]: ...


class WsRemote(Protocol):
    token: str | None

    async def open(self) -> Any: ...
    async def send_commands(
        self, commands: list[SamsungTVCommand], key_press_delay: float | None = None
    ) -> None: ...
    def is_alive(self) -> bool: ...
    async def close(self) -> None: ...


RestFactory = Callable[[str, float], RestClient]
WsFactory = Callable[[str, str | None, float], WsRemote]


class _AioRest:
    """REST ``GET http://<host>:8001/api/v2/`` via ``SamsungTVAsyncRest`` (sessão por chamada)."""

    def __init__(self, host: str, timeout: float) -> None:
        self.host = host
        self.timeout = timeout
        self.url = SamsungTVWSBaseConnection(host, endpoint="", port=REST_PORT)._format_rest_url()

    async def rest_device_info(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            rest = SamsungTVAsyncRest(
                self.host, session=session, port=REST_PORT, timeout=self.timeout
            )
            return await rest.rest_device_info()


def default_rest_factory(host: str, timeout: float) -> _AioRest:
    return _AioRest(host, timeout)


class _ClosingAsyncRemote(SamsungTVWSAsyncRemote):
    """``SamsungTVWSAsyncRemote`` cujo ``open()`` fecha o socket se a conexão falhar.

    Na lib (3.0.6, async_connection.py:47-79) o ``ClientConnection`` é local e só vai
    para ``self.connection`` após ``ms.channel.connect``; cancelamento (timeout do
    "Permitir"), ``ms.channel.unauthorized`` ou evento inesperado deixam o socket
    aberto, pois ``close()`` só age ``if self.connection``. Mesma lógica, com limpeza.
    """

    async def open(self) -> ClientConnection:
        if self.connection:
            return self.connection
        kwargs: dict[str, Any] = {}
        if self._is_ssl_connection():
            kwargs["ssl"] = helper.get_ssl_context()
        conn = await connect(
            self._format_websocket_url(self.endpoint),
            open_timeout=self.timeout,
            close_timeout=self.timeout,
            **kwargs,
        )
        try:
            event: str | None = None
            response: dict[str, Any] = {}
            while event is None or event in IGNORE_EVENTS_AT_STARTUP:
                response = helper.process_api_response(await conn.recv())
                event = response.get("event", "*")
                self._websocket_event(event, response)
            if event == MS_CHANNEL_UNAUTHORIZED:
                raise UnauthorizedError(response)
            if event != MS_CHANNEL_CONNECT_EVENT:
                raise ConnectionFailure(response)
            self._check_for_token(response)
        except BaseException:
            with contextlib.suppress(Exception):
                await conn.close()
            raise
        self.connection = conn
        return conn


def default_ws_factory(host: str, token: str | None, timeout: float) -> SamsungTVWSAsyncRemote:
    # timeout = open_timeout do websockets (TCP + TLS + handshake), não a espera do "Permitir".
    # key_press_delay=0: a lib dorme esse tempo após cada envio (padrão 1 s).
    return _ClosingAsyncRemote(
        host, token=token, port=WS_PORT, timeout=timeout, key_press_delay=0, name=CLIENT_NAME
    )


class LocalChannel:
    def __init__(
        self,
        host: str,
        token: str | None,
        on_token: Callable[[str], None],
        rest_factory: RestFactory = default_rest_factory,
        ws_factory: WsFactory = default_ws_factory,
        connect_timeout_s: float = 4.0,
        pairing_timeout_s: float = 30.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._host = host
        self._token = token
        self._on_token = on_token
        self._rest_factory = rest_factory
        self._ws_factory = ws_factory
        self._connect_timeout_s = connect_timeout_s
        self._pairing_timeout_s = pairing_timeout_s
        self._sleep = sleep
        self._remote: WsRemote | None = None
        self._pairing_pending = False
        self._lock = asyncio.Lock()

    # ---- REST ---------------------------------------------------------------

    async def device_info(self) -> dict[str, Any]:
        rest = self._rest_factory(self._host, self._connect_timeout_s)
        try:
            # Teto extra: aiohttp com timeout já limita, mas o fake/DNS podem não.
            data = await asyncio.wait_for(rest.rest_device_info(), self._connect_timeout_s + 1)
        except Exception as exc:  # HttpApiError, ResponseError, TimeoutError, OSError, aiohttp
            raise TVUnreachable(_UNREACHABLE_MSG) from exc
        device = data.get("device") if isinstance(data, dict) else None
        if not isinstance(device, dict):
            raise TVUnreachable(_UNREACHABLE_MSG)
        return device

    async def power_state(self) -> Literal["on", "standby"] | None:
        try:
            device = await self.device_info()
        except TVUnreachable:
            return None
        state = device.get("PowerState")
        if state is None:
            return "on"  # REST respondeu sem o campo (modelos antigos): está ligada
        state = str(state).lower()
        if state == "on":
            return "on"
        if state == "standby":
            return "standby"
        return None

    async def mac(self) -> str | None:
        mac = (await self.device_info()).get("wifiMac")
        return str(mac).lower() if mac else None

    # ---- WebSocket ----------------------------------------------------------

    @property
    def pairing_pending(self) -> bool:
        return self._pairing_pending

    @property
    def connected(self) -> bool:
        return self._remote is not None and self._remote.is_alive()

    async def _connect_locked(self) -> WsRemote:
        remote = self._ws_factory(self._host, self._token, self._connect_timeout_s)
        pairing = self._token is None
        # Sem token, open() só retorna quando o usuário aceita o "Permitir" na TV.
        # A fase TCP/TLS continua limitada pelo open_timeout da lib (connect_timeout_s),
        # que termina a tarefa com TimeoutError antes do teto de pareamento.
        ceiling = self._pairing_timeout_s if pairing else self._connect_timeout_s
        self._pairing_pending = pairing
        task = asyncio.ensure_future(remote.open())
        try:
            done, _ = await asyncio.wait({task}, timeout=ceiling)
            if not done:
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                await self._discard(remote)
                if pairing:
                    raise AdbUnauthorized(_PAIRING_TIMEOUT_MSG)
                raise TVUnreachable(_UNREACHABLE_MSG)
            try:
                task.result()
            except UnauthorizedError as exc:  # ms.channel.unauthorized
                await self._discard(remote)
                raise AdbUnauthorized(_DENIED_MSG) from exc
            except Exception as exc:  # recusa TCP, TLS, timeout do handshake, ConnectionFailure
                await self._discard(remote)
                raise TVUnreachable(_UNREACHABLE_MSG) from exc
        except BaseException:
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                await self._discard(remote)
            raise
        finally:
            self._pairing_pending = False
        token = remote.token
        if token and token != self._token:
            self._token = token
            self._on_token(token)
        self._remote = remote
        return remote

    @staticmethod
    async def _discard(remote: WsRemote) -> None:
        with contextlib.suppress(Exception):
            await remote.close()

    async def _drop_remote(self) -> None:
        remote, self._remote = self._remote, None
        if remote is not None:
            await self._discard(remote)

    async def _send_locked(self, commands: list[SamsungTVCommand]) -> None:
        remote = self._remote if self.connected else None
        if remote is None:
            await self._drop_remote()
            remote = await self._connect_locked()
        try:
            await remote.send_commands(commands, key_press_delay=0)
            return
        except Exception:
            await self._drop_remote()
        # Conexão caiu: reconecta uma vez e repete.
        remote = await self._connect_locked()
        try:
            await remote.send_commands(commands, key_press_delay=0)
        except Exception as exc:
            await self._drop_remote()
            raise TVUnreachable(_UNREACHABLE_MSG) from exc

    async def _send(self, *commands: SamsungTVCommand) -> None:
        async with self._lock:
            await self._send_locked(list(commands))

    async def reset_token(self) -> None:
        """Esquece o token e fecha o socket: o próximo connect pede "Permitir" (30 s)."""
        async with self._lock:
            await self._drop_remote()
            self._token = None

    async def connect(self) -> None:
        """Abre o WebSocket sem enviar nada (sem token: aguarda o "Permitir" na TV)."""
        async with self._lock:
            if self.connected:
                return
            await self._drop_remote()
            await self._connect_locked()

    async def key(self, samsung_key: str) -> None:
        await self._send(SendRemoteKey.click(samsung_key))

    async def hold(self, samsung_key: str, seconds: float) -> None:
        # Sob o lock inteiro: nenhuma outra tecla entra entre press e release.
        # O release roda num finally blindado: cancelar durante a espera não pode deixar
        # a tecla pressionada com o socket aberto.
        async with self._lock:
            await self._send_locked([SendRemoteKey.press(samsung_key)])
            released = False
            try:
                await self._sleep(seconds)
            finally:
                released = await asyncio.shield(self._release_locked(samsung_key))
            if not released:
                raise TVUnreachable(_UNREACHABLE_MSG)

    async def _release_locked(self, samsung_key: str) -> bool:
        """Release no socket atual; sem socket a TV já descartou o press. Nunca levanta."""
        if not self.connected:
            await self._drop_remote()
            return False
        assert self._remote is not None
        try:
            await self._remote.send_commands([SendRemoteKey.release(samsung_key)], key_press_delay=0)
            return True
        except Exception:
            await self._drop_remote()  # fechar o socket faz a TV soltar a tecla
            return False

    async def run_app(self, app_id: str) -> None:
        await self._send(ChannelEmitCommand.launch_app(app_id, "DEEP_LINK"))

    async def open_browser(self, url: str) -> None:
        await self._send(ChannelEmitCommand.launch_app(BROWSER_APP_ID, "NATIVE_LAUNCH", url))

    async def set_host(self, host: str) -> None:
        async with self._lock:  # serializa com conexões em andamento
            await self._drop_remote()
            self._host = host

    async def close(self) -> None:
        async with self._lock:
            await self._drop_remote()
