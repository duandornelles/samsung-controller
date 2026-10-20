"""Núcleo de roteamento: escolhe o canal de cada comando, liga pela rede, redescobre.

Métodos e retornos espelham o ``TVController`` do sidecar TCL, para a API HTTP
manter o mesmo contrato. Canais: local (REST :8001 + WebSocket :8002), SmartThings
(entrada, imagem, volume) e Wake-on-LAN (ligar).
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar

from . import discovery
from .apps import app_for
from .channels.smartthings import NO_BACKLIGHT_MSG, picture_label
from .channels.wol import send_magic_packet
from .config import Config, config_stamp, load_config, save_config
from .discovery import TVCandidate
from .errors import (
    InputNotConfirmed,
    InvalidValue,
    NoCache,
    NotPaired,
    NotSupported,
    PictureUnreadable,
    TVNotFound,
    TVUnreachable,
    UnknownMode,
)
from .keys import samsung_key

log = logging.getLogger(__name__)

T = TypeVar("T")

POLL_S = 1.0
WOL_WAIT_S = 15.0
INPUT_CONFIRM_S = 5.0
PICTURE_CONFIRM_S = 5.0
HOLD_POWER_S = 3.0
STATE_POWER_TIMEOUT_S = 2.0  # teto do REST de energia dentro do /state
STATE_ST_TIMEOUT_S = 2.5  # teto do SmartThings dentro do /state

# Sentinela que o app usa para "a TV está mostrando uma entrada" (herdada do TCL).
INPUT_APP = "com.tcl.tv"

_HDMI_RE = re.compile(r"^HDMI(\d+)$")
_NO_ST_MSG = "Configure o token SmartThings (samsung smartthings <token>)"
_NO_MAC_MSG = "TV inacessível e sem MAC salvo para ligá-la pela rede"
_WOL_TIMEOUT_MSG = "A TV não ligou após o Wake-on-LAN"
_NOT_PAIRED_MSG = "TV não pareada: aceite o pedido de conexão na TV (samsung pair)"

# Campos do config.json que o sidecar grava; st_token/st_device_id são da CLI.
_OWNED_FIELDS = ("tv_host", "tv_mac", "tv_name", "ws_token")


class Local(Protocol):
    @property
    def connected(self) -> bool: ...
    @property
    def pairing_pending(self) -> bool: ...
    async def power_state(self) -> str | None: ...
    async def mac(self) -> str | None: ...
    async def key(self, samsung_key: str) -> None: ...
    async def hold(self, samsung_key: str, seconds: float) -> None: ...
    async def run_app(self, app_id: str) -> None: ...
    async def open_browser(self, url: str) -> None: ...
    async def connect(self) -> None: ...
    async def reset_token(self) -> None: ...
    async def set_host(self, host: str) -> None: ...
    async def close(self) -> None: ...


class SmartThings(Protocol):
    async def input_sources(self) -> tuple[list[str], str | None]: ...
    async def set_input(self, source: str) -> None: ...
    async def picture_modes(self) -> tuple[list[str], str | None]: ...
    async def set_picture_mode(self, mode: str) -> None: ...
    async def volume(self) -> dict | None: ...
    async def backlight(self) -> int | None: ...
    async def set_backlight(self, v: int) -> None: ...


LocalFactory = Callable[[str, str | None, Callable[[str], None]], Local]
STFactory = Callable[[str, str], SmartThings]
GetMac = Callable[[str], Awaitable[str | None]]
Finder = Callable[[str | None, GetMac], Awaitable[tuple[TVCandidate, str | None]]]


def _hdmi_port(source: str | None) -> int | None:
    m = _HDMI_RE.match(source or "")
    return int(m.group(1)) if m else None


class TVService:
    def __init__(
        self,
        config: Config,
        local_factory: LocalFactory,
        st_factory: STFactory,
        wol: Callable[[str], Awaitable[None]] = send_magic_packet,
        finder: Finder = discovery.find_tv,
        save: Callable[[Config], None] = save_config,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        load: Callable[[], Config] = load_config,
        stamp: Callable[[], object] = config_stamp,
    ) -> None:
        self._config = config
        self._local_factory = local_factory
        self._st_factory = st_factory
        self._wol = wol
        self._finder = finder
        self._save = save
        self._sleep = sleep
        self._now = now
        self._load = load
        self._stamp = stamp
        self._seen_stamp = stamp()  # config já lido na partida
        self._local = local_factory(config.tv_host or "", config.ws_token, self._on_token)
        self._st: SmartThings | None = None
        self._st_key: tuple[str, str] | None = None
        self._st_ok: bool | None = None  # None = nenhuma chamada ainda
        self._picture_lock = asyncio.Lock()
        self._picture_cache: dict[str, Any] | None = None

    # -- persistência / descoberta -------------------------------------------

    def _adopt_disk_st(self, disk: Config) -> None:
        """Adota st_token/st_device_id do disco quando o par está completo lá."""
        if disk.st_token and disk.st_device_id:
            self._config.st_token = disk.st_token
            self._config.st_device_id = disk.st_device_id

    def _persist(self) -> None:
        """Grava só os campos do sidecar sobre o config.json atual do disco.

        A CLI ``samsung smartthings`` grava st_token/st_device_id direto no arquivo
        enquanto o sidecar roda; regravar a cópia da partida apagaria esses campos.
        """
        disk = self._load()
        self._adopt_disk_st(disk)
        for name in _OWNED_FIELDS:
            setattr(disk, name, getattr(self._config, name))
        # Arquivo ausente/ilegível: mantém o par SmartThings que está em memória.
        disk.st_token = self._config.st_token
        disk.st_device_id = self._config.st_device_id
        self._save(disk)
        self._seen_stamp = self._stamp()

    def _refresh_from_disk(self) -> None:
        """Relê o config.json se outro processo o alterou (sem reiniciar o sidecar)."""
        current = self._stamp()
        if current == self._seen_stamp:
            return
        self._seen_stamp = current
        self._adopt_disk_st(self._load())

    def _on_token(self, token: str) -> None:
        self._config.ws_token = token
        self._persist()

    async def _get_mac(self, host: str) -> str | None:
        tmp = self._local_factory(host, None, lambda _token: None)
        try:
            return await tmp.mac()
        finally:
            await tmp.close()

    async def _find(self) -> tuple[TVCandidate, str | None]:
        return await self._finder(self._config.tv_mac, self._get_mac)

    async def _apply(self, cand: TVCandidate, mac: str | None) -> None:
        if cand.host != self._config.tv_host:
            await self._local.set_host(cand.host)
        self._config.tv_host = cand.host
        self._config.tv_name = cand.name
        if mac:
            self._config.tv_mac = mac
        self._persist()

    async def _ensure_host(self) -> bool:
        """Primeiro uso: descobre quando não há host salvo. True se descobriu."""
        if self._config.tv_host is not None:
            return False
        await self._apply(*await self._find())
        return True

    async def _run(self, op: Callable[[], Awaitable[T]]) -> T:
        """Roda op; em TVUnreachable redescobre uma vez e repete se o IP mudou."""
        discovered = await self._ensure_host()
        try:
            return await op()
        except TVUnreachable as exc:
            if discovered:
                raise
            try:
                cand, mac = await self._find()
            except TVNotFound:
                raise exc from None
            if cand.host == self._config.tv_host:
                raise
            await self._apply(cand, mac)
            return await op()

    # -- SmartThings ---------------------------------------------------------

    def _st_channel(self) -> SmartThings | None:
        self._refresh_from_disk()
        token, device = self._config.st_token, self._config.st_device_id
        if not token or not device:
            return None
        if self._st is None or self._st_key != (token, device):
            self._st = self._st_factory(token, device)
            self._st_key = (token, device)
            self._st_ok = None
        return self._st

    def _require_st(self) -> SmartThings:
        st = self._st_channel()
        if st is None:
            raise NotSupported(_NO_ST_MSG)
        return st

    async def _st_call(self, call: Awaitable[T]) -> T:
        """Executa uma chamada SmartThings registrando se o canal respondeu."""
        try:
            result = await call
        except TVUnreachable:
            self._st_ok = False
            raise
        except NotSupported as exc:
            # Brilho ausente é limitação da TV, não falha do SmartThings.
            self._st_ok = exc.message == NO_BACKLIGHT_MSG
            raise
        self._st_ok = True
        return result

    def _channels(self) -> dict[str, bool]:
        st_up = self._st_channel() is not None and self._st_ok is not False
        return {"remote": bool(self._local.connected), "adb": st_up}

    def _adb_auth(self) -> str | None:
        return "pending" if self._local.pairing_pending else None

    # -- teclas, apps, estado ------------------------------------------------

    async def _power(self, woke: list[bool]) -> str:
        """Liga por WOL ou desliga segurando KEY_POWER.

        ``woke`` sobrevive à repetição do _run: se o WOL já foi enviado nesta
        operação (ex.: o IP mudou e a redescoberta achou a TV ligando no IP novo),
        a TV ligada é resultado do WOL e não pode ser desligada.
        """
        if await self._local.power_state() == "on":
            if woke[0]:
                return "wol"
            # Na Frame um toque curto entra no Modo Arte; segurar 3 s desliga.
            await self._local.hold("KEY_POWER", HOLD_POWER_S)
            return "remote"
        mac = self._config.tv_mac
        if not mac:
            raise TVUnreachable(_NO_MAC_MSG)
        await self._wol(mac)
        woke[0] = True
        for _ in range(round(WOL_WAIT_S / POLL_S)):
            await self._sleep(POLL_S)
            if await self._local.power_state() == "on":
                return "wol"
        raise TVUnreachable(_WOL_TIMEOUT_MSG)

    async def send_key(self, name: str) -> str:
        key = samsung_key(name)
        if key == "KEY_POWER":
            woke = [False]
            return await self._run(lambda: self._power(woke))

        async def op() -> str:
            await self._local.key(key)
            return "remote"

        return await self._run(op)

    async def launch_app(self, link: str) -> None:
        app_id = app_for(link)

        async def op() -> None:
            if app_id is not None:
                await self._local.run_app(app_id)
            else:
                await self._local.open_browser(link)

        await self._run(op)

    async def _st_state(self, st: SmartThings) -> tuple[dict | None, str | None]:
        """(volume, app) pelo SmartThings; falha ou lentidão vira (None, None).

        Limitado a STATE_ST_TIMEOUT_S: o app dá timeout de 5 s no /state e a
        nuvem tem timeout de 10 s. TaskGroup cancela a outra leitura se uma falhar.
        """
        try:
            async with asyncio.timeout(STATE_ST_TIMEOUT_S):
                async with asyncio.TaskGroup() as tg:
                    vol_task = tg.create_task(st.volume())
                    src_task = tg.create_task(st.input_sources())
        except Exception:  # ExceptionGroup (TVUnreachable/NotSupported) ou TimeoutError
            log.debug("state: SmartThings indisponível", exc_info=True)
            self._st_ok = False
            return None, None
        self._st_ok = True
        _, source = src_task.result()
        return vol_task.result(), INPUT_APP if _hdmi_port(source) is not None else None

    async def state(self) -> dict[str, Any]:
        """Nunca levanta; sem descoberta nem redescoberta."""
        power: str | None = None
        volume: dict | None = None
        app: str | None = None
        if self._config.tv_host is not None:
            try:
                # Teto curto: o REST da TV fora da rede leva ~4-5 s e o app desiste em 5 s.
                async with asyncio.timeout(STATE_POWER_TIMEOUT_S):
                    power = await self._local.power_state()
            except Exception:  # TimeoutError incluso
                power = None
            if power != "on":
                power = "standby"
            st = self._st_channel()
            if st is not None and power == "on":
                volume, app = await self._st_state(st)
        return {
            "power": power,
            "app": app,
            "volume": volume,
            "channels": self._channels(),
            "adb_auth": self._adb_auth(),
        }

    async def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tv_host": self._config.tv_host,
            "tv_mac": self._config.tv_mac,
            "channels": self._channels(),
            "adb_auth": self._adb_auth(),
        }

    # -- pareamento ----------------------------------------------------------

    async def start_pairing(self) -> None:
        """Abre o WebSocket sem token: a TV mostra "Permitir" e o novo token é salvo.

        Sempre sem token (spec §4.2): um token salvo pode ter sido revogado na TV, e
        conectar com ele usaria o teto de 4 s em vez dos 30 s do pareamento, sem
        ``adb_auth = "pending"``. O token antigo é descartado também na config, para
        ``finish_pairing`` não confirmar um pareamento que falhou.
        """
        if self._config.tv_host is None or self._config.tv_mac is None:
            await self._apply(*await self._find())
        await self._local.reset_token()
        if self._config.ws_token is not None:
            self._config.ws_token = None
            self._persist()
        await self._local.connect()

    async def finish_pairing(self, pin: str) -> None:
        # A Samsung não usa PIN: basta já haver token salvo.
        if not self._config.ws_token:
            raise NotPaired(_NOT_PAIRED_MSG)

    # -- entradas (SmartThings) ----------------------------------------------

    async def _read_inputs(self, st: SmartThings) -> list[dict[str, Any]]:
        sources, current = await self._st_call(st.input_sources())
        result = []
        for source in sources:
            port = _hdmi_port(source)
            if port is None:
                continue
            result.append(
                {
                    "port": port,
                    "id": source,
                    "label": f"HDMI {port}",
                    "connected": False,
                    "active": source == current,
                }
            )
        return result

    async def inputs(self) -> list[dict[str, Any]]:
        # Leitura (poll do app): sem descoberta/redescoberta.
        return await self._read_inputs(self._require_st())

    # Entrada e imagem usam só a nuvem SmartThings: não dependem do IP da TV, então
    # não passam por _run (redescobrir a TV local não ajuda quando a nuvem falha).

    async def set_input(self, port: int) -> dict[str, Any]:
        st = self._require_st()
        inputs = await self._read_inputs(st)
        target = next((i for i in inputs if i["port"] == port), None)
        if target is None:
            valid = ", ".join(str(i["port"]) for i in inputs) or "nenhuma"
            raise InvalidValue(f"Porta HDMI {port} não existe (válidas: {valid})")
        await self._st_call(st.set_input(target["id"]))
        # O modo de imagem é por entrada: o cache deixa de valer assim que a troca é pedida.
        self._picture_cache = None
        for _ in range(round(INPUT_CONFIRM_S / POLL_S)):
            await self._sleep(POLL_S)
            _, current = await self._st_call(st.input_sources())
            if current == target["id"]:
                return {"ok": True, "active_port": port}
        raise InputNotConfirmed(f"A TV não confirmou a troca para HDMI {port}")

    # -- imagem (SmartThings) ------------------------------------------------

    async def _read_picture(self, st: SmartThings) -> dict[str, Any]:
        modes, current = await self._st_call(st.picture_modes())
        if current is None:
            raise PictureUnreadable("Não foi possível ler o modo de imagem da TV")
        backlight = await self._st_call(st.backlight())
        self._picture_cache = {
            "mode": picture_label(current),
            "mode_id": current,
            "modes": [{"id": m, "label": picture_label(m)} for m in (modes or [current])],
            "backlight": backlight if backlight is not None else 0,
            "cached_at": self._now().isoformat(),
        }
        return dict(self._picture_cache)

    def _touch_cache(self, **changes: Any) -> None:
        if self._picture_cache is not None:
            self._picture_cache.update(changes, cached_at=self._now().isoformat())

    async def picture(self, cached: bool = False) -> dict[str, Any]:
        st = self._require_st()
        if cached:
            if self._picture_cache is None:
                raise NoCache("Nenhuma leitura de imagem em cache")
            return dict(self._picture_cache)
        async with self._picture_lock:
            return await self._read_picture(st)

    async def set_picture_mode(self, label: str) -> dict[str, Any]:
        st = self._require_st()
        async with self._picture_lock:
            modes, _ = await self._st_call(st.picture_modes())
            wanted = label.strip().casefold()
            mode_id = next(
                (m for m in modes if picture_label(m).casefold() == wanted), None
            ) or next((m for m in modes if m.casefold() == wanted), None)
            if mode_id is None:
                valid = ", ".join(picture_label(m) for m in modes)
                raise UnknownMode(f"Modo de imagem desconhecido: {label} (válidos: {valid})")
            tv_label = picture_label(mode_id)
            await self._st_call(st.set_picture_mode(mode_id))
            for _ in range(round(PICTURE_CONFIRM_S / POLL_S)):
                await self._sleep(POLL_S)
                _, current = await self._st_call(st.picture_modes())
                if current == mode_id:
                    self._touch_cache(mode=tv_label, mode_id=mode_id)
                    return {"ok": True, "mode": tv_label, "mode_id": mode_id}
            raise PictureUnreadable(f"A TV não confirmou o modo de imagem {tv_label}")

    async def set_backlight(self, value: int) -> dict[str, Any]:
        st = self._require_st()
        if not 0 <= value <= 100:
            raise InvalidValue(f"Brilho deve estar entre 0 e 100 (recebido {value})")
        async with self._picture_lock:
            await self._st_call(st.set_backlight(value))
            self._touch_cache(backlight=value)
            return {"ok": True, "backlight": value}

    # -- ciclo de vida -------------------------------------------------------

    async def warmup(self) -> None:
        """Conecta o WebSocket na partida se já houver token; nunca levanta.

        Sem token não conecta: abriria o "Permitir" na TV sem o usuário pedir.
        """
        if not self._config.tv_host or not self._config.ws_token:
            return
        try:
            await self._local.connect()
        except Exception:
            log.warning("warmup: falha ao conectar o WebSocket", exc_info=True)

    async def close(self) -> None:
        await self._local.close()
