"""Contrato com o TVService REAL (canais falsos): saída validada contra os modelos Swift.

None só é aceito onde o campo é Optional em app/Sources/TCLCore/Models.swift.
"""

import warnings

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*httpx2.*")
    from fastapi.testclient import TestClient

from fakes import Harness
from samsung_sidecar.api import create_app

CHANNELS = {"remote": bool, "adb": bool}
HEALTH = {"ok": bool, "tv_host": "str?", "tv_mac": "str?", "channels": CHANNELS, "adb_auth": "str?"}
VOLUME = {"level": int, "max": int, "muted": bool}
STATE = {"power": "str?", "app": "str?", "volume": ("opt", VOLUME), "channels": CHANNELS,
         "adb_auth": "str?"}
INPUT = {"port": int, "id": str, "label": str, "connected": bool, "active": bool}
PICTURE = {"mode": str, "mode_id": str, "modes": [{"id": str, "label": str}], "backlight": int,
           "cached_at": str}


def check(value, schema, path="$"):
    if schema == "str?":
        assert value is None or isinstance(value, str), (path, value)
    elif isinstance(schema, tuple):  # ("opt", sub)
        if value is not None:
            check(value, schema[1], path)
    elif isinstance(schema, dict):
        assert isinstance(value, dict), (path, value)
        assert set(value) == set(schema), (path, set(value) ^ set(schema))
        for k, sub in schema.items():
            check(value[k], sub, f"{path}.{k}")
    elif isinstance(schema, list):
        assert isinstance(value, list), (path, value)
        assert value, path
        for i, item in enumerate(value):
            check(item, schema[0], f"{path}[{i}]")
    else:
        assert type(value) is schema, (path, value, schema)


def client_for(h):
    return TestClient(create_app(h.svc), base_url="http://127.0.0.1:8766")


def test_health_antes_da_descoberta():
    h = Harness(st=False, tv_host=None, tv_mac=None, ws_token=None)
    with client_for(h) as c:
        body = c.get("/health").json()
    check(body, HEALTH)
    assert body["tv_host"] is None


def test_health_depois_da_descoberta():
    h = Harness()
    with client_for(h) as c:
        body = c.get("/health").json()
    check(body, HEALTH)
    assert isinstance(body["tv_host"], str) and isinstance(body["tv_mac"], str)


def test_state_on_com_smartthings():
    h = Harness()
    with client_for(h) as c:
        body = c.get("/state").json()
    check(body, STATE)
    assert body["power"] == "on" and body["app"] == "com.tcl.tv"
    assert isinstance(body["volume"], dict)


def test_state_standby_sem_smartthings():
    h = Harness(st=False)
    h.local.powers = ["standby"]
    with client_for(h) as c:
        body = c.get("/state").json()
    check(body, STATE)
    assert body["power"] == "standby" and body["app"] is None and body["volume"] is None


def test_state_tv_desconhecida():
    h = Harness(st=False, tv_host=None, tv_mac=None)
    with client_for(h) as c:
        body = c.get("/state").json()
    check(body, STATE)
    assert body["power"] is None


def test_key_remote():
    h = Harness()
    with client_for(h) as c:
        body = c.post("/key/home").json()
    check(body, {"ok": bool, "channel": str})
    assert body["channel"] == "remote"


def test_key_power_wol():
    h = Harness()
    h.local.powers = ["standby", "on"]
    with client_for(h) as c:
        body = c.post("/key/power").json()
    check(body, {"ok": bool, "channel": str})
    assert body["channel"] == "wol"


def test_inputs():
    h = Harness()
    with client_for(h) as c:
        body = c.get("/inputs").json()
    check(body, [INPUT])
    assert [i["port"] for i in body] == [1, 2]


def test_set_input():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "inputs_seq", ["HDMI1", "HDMI2"])
    with client_for(h) as c:
        body = c.post("/input/2").json()
    check(body, {"ok": bool, "active_port": int})
    assert body["active_port"] == 2


def test_picture():
    h = Harness()
    with client_for(h) as c:
        body = c.get("/picture").json()
        cached = c.get("/picture?cached=1").json()
    check(body, PICTURE)
    check(cached, PICTURE)


def test_picture_backlight_ausente_vira_zero_int():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "bl", None)
    with client_for(h) as c:
        body = c.get("/picture").json()
    check(body, PICTURE)
    assert body["backlight"] == 0


def test_picture_mode():
    h = Harness()
    h.st_setup = lambda st: setattr(st, "mode_seq", ["Standard", "Movie"])
    with client_for(h) as c:
        body = c.post("/picture/mode", json={"mode": "Filme"}).json()
    check(body, {"ok": bool, "mode": str, "mode_id": str})
    assert body["mode"] == "Filme"


def test_picture_backlight():
    h = Harness()
    with client_for(h) as c:
        body = c.post("/picture/backlight", json={"value": 60}).json()
    check(body, {"ok": bool, "backlight": int})
    assert body["backlight"] == 60


def test_sem_smartthings_501():
    h = Harness(st=False)
    with client_for(h) as c:
        r = c.get("/inputs")
    assert r.status_code == 501
    check(r.json(), {"error": str, "message": str})


@pytest.mark.parametrize("path,body", [("/pair/start", None), ("/app", {"link": "https://youtube.com"})])
def test_ok_routes(path, body):
    h = Harness()
    with client_for(h) as c:
        r = c.post(path, json=body) if body else c.post(path)
    assert r.status_code == 200
    check(r.json(), {"ok": bool})
