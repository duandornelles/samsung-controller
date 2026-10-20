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

from fakes import MAC, NOW, FakeLocal, FakeST, Harness  # noqa: F401


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


async def test_power_wol_then_rediscovery_does_not_turn_tv_off():
    # IP mudou: WOL acorda a TV, mas o IP antigo nunca responde; a redescoberta
    # acha o IP novo e a TV já está ligada -> não pode segurar KEY_POWER.
    h = Harness()
    h.local.powers = [None] * 16 + ["on"]
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    assert await h.svc.send_key("power") == "wol"
    assert h.wol_calls == [MAC]
    assert not any(c[0] == "hold" for c in h.local.calls)
    assert h.config.tv_host == "10.0.0.9"


async def test_start_pairing_forces_tokenless_connect():
    h = Harness(ws_token="stale")
    h.local.connect_token = "fresh"
    await h.svc.start_pairing()
    assert h.local.calls[:2] == [("reset_token",), ("connect",)]
    assert h.config.ws_token == "fresh" and h.saved[-1].ws_token == "fresh"


async def test_start_pairing_failure_leaves_no_token():
    h = Harness(ws_token="stale")
    h.local.errors = [AdbUnauthorized("expirou")]
    with pytest.raises(AdbUnauthorized):
        await h.svc.start_pairing()
    assert h.config.ws_token is None and h.saved[-1].ws_token is None
    with pytest.raises(NotPaired):
        await h.svc.finish_pairing("0000")


async def test_state_power_probe_is_capped(monkeypatch):
    import asyncio

    from samsung_sidecar import service

    monkeypatch.setattr(service, "STATE_POWER_TIMEOUT_S", 0.05)
    h = Harness()

    async def hang():
        await asyncio.Event().wait()

    h.local.power_hook = hang
    state = await asyncio.wait_for(h.svc.state(), 1.0)
    assert state["power"] == "standby" and state["volume"] is None


# -- I1: token SmartThings gravado pela CLI com o sidecar rodando ---------------


async def test_cli_smartthings_write_picked_up_without_restart():
    h = Harness(st=False)
    with pytest.raises(NotSupported):
        await h.svc.inputs()
    h.cli_write(st_token="pat2", st_device_id="dev2")
    assert [i["port"] for i in await h.svc.inputs()] == [1, 2]
    assert (h.st.token, h.st.device_id) == ("pat2", "dev2")
    assert (await h.svc.health())["channels"]["adb"] is True


async def test_sidecar_save_preserves_cli_smartthings_fields():
    h = Harness(st=False, ws_token=None)
    h.cli_write(st_token="pat2", st_device_id="dev2")
    # Salvamentos do sidecar (token novo, redescoberta) sem ler /inputs antes.
    h.svc._on_token("newtok")
    assert (h.disk.st_token, h.disk.st_device_id, h.disk.ws_token) == ("pat2", "dev2", "newtok")
    h.local.errors = [TVUnreachable("x")]
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    await h.svc.send_key("home")
    assert (h.disk.st_token, h.disk.st_device_id, h.disk.tv_host) == ("pat2", "dev2", "10.0.0.9")


async def test_sidecar_save_keeps_owned_fields_from_memory():
    h = Harness()
    h.cli_write(tv_host="1.2.3.4", ws_token="alheio")
    h.svc._on_token("meu")
    assert (h.disk.tv_host, h.disk.ws_token) == ("10.0.0.5", "meu")


async def test_real_disk_cli_write_then_sidecar_save(home):
    from samsung_sidecar.config import load_config, save_config

    save_config(Config(tv_host="10.0.0.5", tv_mac=MAC, ws_token="tok"))
    sts: list[FakeST] = []

    def st_factory(token, device):
        sts.append(FakeST(token, device))
        return sts[-1]

    svc = TVService(load_config(), FakeLocal, st_factory)
    with pytest.raises(NotSupported):
        await svc.inputs()
    cfg = load_config()  # o que `samsung smartthings` faz
    cfg.st_token, cfg.st_device_id = "pat", "dev"
    save_config(cfg)
    assert [i["port"] for i in await svc.inputs()] == [1, 2]
    svc._on_token("tok2")
    disk = load_config()
    assert (disk.st_token, disk.st_device_id, disk.ws_token) == ("pat", "dev", "tok2")


# -- I3: ligar pela rede tem prazo total ---------------------------------------


async def _hang():
    import asyncio

    await asyncio.Event().wait()


async def test_power_hanging_probe_bounded_by_deadline(monkeypatch):
    import asyncio
    import time

    from samsung_sidecar import service

    monkeypatch.setattr(service, "POWER_POLL_CAP_S", 0.01)
    h = Harness()
    h.local.power_hook = _hang  # REST da TV nunca responde
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    t0 = time.monotonic()
    with pytest.raises(TVUnreachable):
        await asyncio.wait_for(h.svc.send_key("power"), 5)
    assert time.monotonic() - t0 < 3
    assert h.clock_now <= service.POWER_DEADLINE_S
    assert sum(h.sleeps) <= service.POWER_DEADLINE_S
    assert h.wol_calls == [MAC]  # o retry no IP novo não reenvia nem dobra a espera


async def test_power_retry_after_wol_shares_deadline():
    from samsung_sidecar import service

    h = Harness()
    h.local.powers = ["standby"]
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    with pytest.raises(TVUnreachable):
        await h.svc.send_key("power")
    assert h.finder_calls == [MAC]
    assert h.wol_calls == [MAC]
    assert sum(h.sleeps) <= service.POWER_DEADLINE_S


async def test_power_no_rediscovery_after_deadline(monkeypatch):
    from samsung_sidecar import service

    monkeypatch.setattr(service, "POWER_DEADLINE_S", 10.0)
    h = Harness()
    h.local.powers = ["standby"]
    h.finder_result = (TVCandidate("10.0.0.9", "[TV] Frame"), MAC)
    with pytest.raises(TVUnreachable):
        await h.svc.send_key("power")
    assert h.finder_calls == []
    assert sum(h.sleeps) == 10.0


async def test_power_rediscovery_capped_by_remaining_time(monkeypatch):
    import asyncio

    from samsung_sidecar import service

    monkeypatch.setattr(service, "POWER_DEADLINE_S", service.WOL_WAIT_S + 0.05)
    h = Harness()
    h.local.powers = ["standby"]
    h.finder_hook = _hang
    with pytest.raises(TVUnreachable):
        await asyncio.wait_for(h.svc.send_key("power"), 2)
    assert h.finder_calls == [MAC]
