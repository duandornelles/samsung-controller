from datetime import datetime, timezone

import pytest

from samsung_sidecar.config import Config
from samsung_sidecar.discovery import TVCandidate
from samsung_sidecar.errors import (
    AdbUnauthorized,
    InputNotConfirmed,
    InvalidValue,
    NoCache,
    NotPaired,
    NotSupported,
    PictureUnreadable,
    TVNotFound,
    TVUnreachable,
    UnknownKey,
    UnknownMode,
)
from samsung_sidecar.service import TVService

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

    async def power_state(self):
        self.calls.append(("power_state",))
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


# -- teclas / energia ----------------------------------------------------------


async def test_power_from_standby_uses_wol_and_waits():
    h = Harness()
    h.local.powers = ["standby", "standby", "on"]
    assert await h.svc.send_key("power") == "wol"
    assert h.wol_calls == [MAC]
    assert h.sleeps == [1.0, 1.0]
    assert not any(c[0] in ("hold", "key") for c in h.local.calls)


async def test_power_unreachable_tv_also_uses_wol():
    h = Harness()
    h.local.powers = [None, "on"]
    assert await h.svc.send_key("power") == "wol"
    assert h.wol_calls == [MAC]


async def test_power_wol_timeout_unreachable():
    h = Harness()
    h.local.powers = ["standby"]
    h.finder_result = TVNotFound("x")
    with pytest.raises(TVUnreachable):
        await h.svc.send_key("power")
    assert h.wol_calls == [MAC]
    assert h.sleeps == [1.0] * 15


async def test_power_without_mac_unreachable():
    h = Harness(tv_mac=None)
    h.local.powers = ["standby"]
    h.finder_result = TVNotFound("x")
    with pytest.raises(TVUnreachable):
        await h.svc.send_key("power")
    assert h.wol_calls == []


async def test_power_when_on_holds_3s():
    h = Harness()
    assert await h.svc.send_key("power") == "remote"
    assert ("hold", "KEY_POWER", 3.0) in h.local.calls
    assert h.wol_calls == []


async def test_keys_map_to_local():
    h = Harness()
    assert await h.svc.send_key("back") == "remote"
    assert h.local.calls == [("key", "KEY_RETURN")]


async def test_unknown_key():
    h = Harness()
    with pytest.raises(UnknownKey):
        await h.svc.send_key("nope")
    assert h.local.calls == []


async def test_key_rediscovers_once_on_unreachable():
    h = Harness()
    h.local.errors = [TVUnreachable("x")]
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    assert await h.svc.send_key("home") == "remote"
    assert h.finder_calls == [MAC]
    assert ("set_host", "10.0.0.9") in h.local.calls
    assert h.local.calls.count(("key", "KEY_HOME")) == 2
    assert h.config.tv_host == "10.0.0.9" and h.saved[-1].tv_host == "10.0.0.9"


async def test_key_unreachable_same_host_raises():
    h = Harness()
    h.local.errors = [TVUnreachable("x")]
    with pytest.raises(TVUnreachable):
        await h.svc.send_key("home")
    assert h.local.calls.count(("key", "KEY_HOME")) == 1


async def test_launch_known_and_unknown_link():
    h = Harness()
    await h.svc.launch_app("https://www.netflix.com")
    await h.svc.launch_app("https://example.com/x")
    assert h.local.calls == [
        ("run_app", "3201907018807"),
        ("open_browser", "https://example.com/x"),
    ]


# -- estado / saúde ------------------------------------------------------------


async def test_state_pending_pairing():
    h = Harness()
    h.local.pairing_pending = True
    state = await h.svc.state()
    assert state["adb_auth"] == "pending"
    assert (await h.svc.health())["adb_auth"] == "pending"


async def test_state_volume_from_smartthings_or_none():
    h = Harness()
    h.local.connected = True
    assert await h.svc.state() == {
        "power": "on",
        "app": "com.tcl.tv",  # inputSource HDMI1
        "volume": {"level": 12, "max": 100, "muted": False},
        "channels": {"remote": True, "adb": True},
        "adb_auth": None,
    }
    no_st = Harness(st=False)
    assert await no_st.svc.state() == {
        "power": "on",
        "app": None,
        "volume": None,
        "channels": {"remote": False, "adb": False},
        "adb_auth": None,
    }
    assert no_st.sts == []


async def test_state_app_null_when_input_not_hdmi():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "inputs_seq", ["digitalTv"])
    assert (await h.svc.state())["app"] is None


async def test_state_standby_and_unreachable_never_raise():
    h = Harness()
    h.local.powers = [None]
    state = await h.svc.state()
    assert state["power"] == "standby" and state["volume"] is None and state["app"] is None


async def test_state_smartthings_failure_marks_adb_false():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "error", TVUnreachable("x"))
    state = await h.svc.state()
    assert state["power"] == "on" and state["volume"] is None and state["app"] is None
    assert state["channels"]["adb"] is False
    assert h.finder_calls == []


async def test_state_without_host_does_not_probe():
    h = Harness(tv_host=None)
    state = await h.svc.state()
    assert state["power"] is None and state["volume"] is None
    assert h.local.calls == [] and h.finder_calls == []


async def test_health():
    h = Harness()
    assert await h.svc.health() == {
        "ok": True,
        "tv_host": "10.0.0.5",
        "tv_mac": MAC,
        "channels": {"remote": False, "adb": True},
        "adb_auth": None,
    }
    assert (await Harness(st=False).svc.health())["channels"]["adb"] is False


# -- pareamento ----------------------------------------------------------------


async def test_pairing_saves_token_and_finish_accepts_any_pin():
    h = Harness(ws_token=None)
    with pytest.raises(NotPaired):
        await h.svc.finish_pairing("0000")
    h.local.connect_token = "newtok"
    await h.svc.start_pairing()
    assert ("connect",) in h.local.calls
    assert h.config.ws_token == "newtok" and h.saved[-1].ws_token == "newtok"
    await h.svc.finish_pairing("1234")


async def test_start_pairing_denied_propagates():
    h = Harness(ws_token=None)
    h.local.errors = [AdbUnauthorized("recusado")]
    with pytest.raises(AdbUnauthorized):
        await h.svc.start_pairing()


async def test_local_created_with_saved_host_and_token():
    h = Harness()
    assert (h.local.host, h.local.token) == ("10.0.0.5", "tok")


# -- entradas ------------------------------------------------------------------


async def test_inputs_without_smartthings_501():
    h = Harness(st=False)
    for call in (
        h.svc.inputs(),
        h.svc.set_input(1),
        h.svc.picture(),
        h.svc.picture(cached=True),
        h.svc.set_picture_mode("Filme"),
        h.svc.set_backlight(10),
    ):
        with pytest.raises(NotSupported, match="samsung smartthings <token>"):
            await call


async def test_inputs_mapping():
    h = Harness()
    assert await h.svc.inputs() == [
        {"port": 1, "id": "HDMI1", "label": "HDMI 1", "connected": False, "active": True},
        {"port": 2, "id": "HDMI2", "label": "HDMI 2", "connected": False, "active": False},
    ]
    assert h.finder_calls == []


async def test_inputs_unreachable_no_rediscovery():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "error", TVUnreachable("x"))
    with pytest.raises(TVUnreachable):
        await h.svc.inputs()
    assert h.finder_calls == []


async def test_set_input_confirm_and_invalid():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "inputs_seq", ["HDMI1", "HDMI1", "HDMI2"])
    assert await h.svc.set_input(2) == {"ok": True, "active_port": 2}
    assert h.st.commands == [("set_input", "HDMI2")]
    assert h.sleeps == [1.0, 1.0]

    with pytest.raises(InvalidValue, match="1, 2"):
        await h.svc.set_input(3)
    assert h.st.commands == [("set_input", "HDMI2")]


async def test_set_input_not_confirmed():
    h = Harness()
    with pytest.raises(InputNotConfirmed):
        await h.svc.set_input(2)
    assert h.sleeps == [1.0] * 5


# -- imagem --------------------------------------------------------------------


async def test_picture_and_cache_invalidation():
    h = Harness()
    with pytest.raises(NoCache):
        await h.svc.picture(cached=True)
    pic = await h.svc.picture()
    assert pic == {
        "mode": "Padrão",
        "mode_id": "Standard",
        "modes": [
            {"id": "Dynamic", "label": "Dinâmico"},
            {"id": "Standard", "label": "Padrão"},
            {"id": "Movie", "label": "Filme"},
            {"id": "FILMMAKER MODE", "label": "Filmmaker"},
            {"id": "Vivid", "label": "Vivid"},
        ],
        "backlight": 40,
        "cached_at": NOW.isoformat(),
    }
    assert await h.svc.picture(cached=True) == pic
    h.st.inputs_seq = ["HDMI2"]
    await h.svc.set_input(2)
    with pytest.raises(NoCache):
        await h.svc.picture(cached=True)


async def test_picture_backlight_missing_is_zero_and_mode_missing_unreadable():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "bl", None)
    assert (await h.svc.picture())["backlight"] == 0
    h.st.mode_seq = [None]
    with pytest.raises(PictureUnreadable):
        await h.svc.picture()


async def test_set_picture_mode_by_label_confirms_and_updates_cache():
    h = Harness()
    await h.svc.picture()
    h.st.mode_seq = ["Standard", "Movie"]
    assert await h.svc.set_picture_mode("filme") == {"ok": True, "mode": "Filme", "mode_id": "Movie"}
    assert h.st.commands == [("set_picture_mode", "Movie")]
    cached = await h.svc.picture(cached=True)
    assert cached["mode"] == "Filme" and cached["mode_id"] == "Movie"


async def test_set_picture_mode_not_confirmed():
    h = Harness()
    with pytest.raises(PictureUnreadable):
        await h.svc.set_picture_mode("Filme")


async def test_set_picture_mode_unknown():
    h = Harness()
    with pytest.raises(UnknownMode, match="Dinâmico"):
        await h.svc.set_picture_mode("Jogo")
    assert h.st.commands == []


async def test_set_backlight_ok_and_invalid():
    h = Harness()
    await h.svc.picture()
    assert await h.svc.set_backlight(60) == {"ok": True, "backlight": 60}
    assert h.st.commands == [("set_backlight", 60)]
    assert (await h.svc.picture(cached=True))["backlight"] == 60
    with pytest.raises(InvalidValue):
        await h.svc.set_backlight(101)


async def test_backlight_not_supported():
    h = Harness()
    h.st_setup = lambda st: setattr(
        st, "backlight_error", NotSupported("Brilho não disponível nesta TV")
    )
    with pytest.raises(NotSupported, match="Brilho"):
        await h.svc.set_backlight(50)
    # Brilho ausente não significa SmartThings fora do ar.
    assert (await h.svc.health())["channels"]["adb"] is True


# -- descoberta / ciclo de vida ------------------------------------------------


async def test_first_use_discovers_and_saves():
    h = Harness(tv_host=None, tv_mac=None)
    h.finder_result = (TVCandidate("10.0.0.7", "[TV] Samsung Frame"), MAC)
    assert await h.svc.send_key("home") == "remote"
    assert h.finder_calls == [None]
    assert ("set_host", "10.0.0.7") in h.local.calls
    assert (h.config.tv_host, h.config.tv_mac, h.config.tv_name) == (
        "10.0.0.7",
        MAC,
        "[TV] Samsung Frame",
    )
    assert h.saved[-1].tv_host == "10.0.0.7"
    # get_mac do finder consulta o REST do candidato com um canal temporário.
    assert await h.get_mac("10.0.0.8") == MAC
    assert h.locals[-1].host == "10.0.0.8" and h.locals[-1].closed


async def test_first_use_discovery_failure_raises_not_found():
    h = Harness(tv_host=None)
    h.finder_result = TVNotFound("TV não encontrada na rede")
    with pytest.raises(TVNotFound):
        await h.svc.send_key("home")


async def test_warmup_connects_only_with_token_and_never_raises():
    h = Harness()
    h.local.errors = [TVUnreachable("x")]
    await h.svc.warmup()
    assert ("connect",) in h.local.calls
    no_token = Harness(ws_token=None)
    await no_token.svc.warmup()
    assert no_token.local.calls == []


async def test_close():
    h = Harness()
    await h.svc.close()
    assert h.local.closed


async def test_state_smartthings_slow_is_capped(monkeypatch):
    import asyncio

    from samsung_sidecar import service

    monkeypatch.setattr(service, "STATE_ST_TIMEOUT_S", 0.05)
    h = Harness()

    async def hang():
        await asyncio.Event().wait()

    h.st_setup = lambda st: setattr(st, "volume", hang)
    state = await h.svc.state()
    assert state["power"] == "on" and state["volume"] is None and state["app"] is None
    assert state["channels"]["adb"] is False
