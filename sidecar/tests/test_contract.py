"""Contrato app <-> sidecar: mesmas chaves e tipos dos fixtures que o app Swift decodifica."""

import json
from pathlib import Path

import warnings

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*httpx2.*")
    from fastapi.testclient import TestClient

from samsung_sidecar import errors
from samsung_sidecar.api import create_app

FIX = Path(__file__).parent / "fixtures" / "contract"


def fx(name):
    return json.loads((FIX / f"{name}.json").read_text())


def shape(v, path="$"):
    """Chaves e tipos (recursivo); null e tipos de lista tratados pelo primeiro item."""
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__


def assert_same_shape(actual, expected):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), (actual, expected)
        assert set(actual) == set(expected)
        for k in expected:
            assert_same_shape(actual[k], expected[k])
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        if expected:
            assert actual
            assert_same_shape(actual[0], expected[0])
    else:
        assert type(actual) is type(expected), (actual, expected)


class Fake:
    """Devolve exatamente o que o fixture documenta (mudando só os valores)."""

    def __init__(self):
        self.state_name = "state_on"
        self.fail: Exception | None = None

    def _maybe(self):
        if self.fail:
            raise self.fail

    async def warmup(self): ...
    async def close(self): ...

    async def health(self):
        self._maybe()
        return fx("health") | {"tv_host": "10.0.0.2"}

    async def state(self):
        return fx(self.state_name)

    async def start_pairing(self):
        self._maybe()

    async def finish_pairing(self, pin):
        self._maybe()

    async def send_key(self, name):
        self._maybe()
        return "remote"

    async def launch_app(self, link):
        self._maybe()

    async def inputs(self):
        self._maybe()
        return fx("inputs")

    async def set_input(self, port):
        self._maybe()
        return {"ok": True, "active_port": port}

    async def picture(self, cached=False):
        self._maybe()
        return fx("picture")

    async def set_picture_mode(self, mode):
        self._maybe()
        return {"ok": True, "mode": mode, "mode_id": "Game"}

    async def set_backlight(self, value):
        self._maybe()
        return {"ok": True, "backlight": value}


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def client(fake):
    with TestClient(
        create_app(fake), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    ) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert_same_shape(r.json(), fx("health"))


@pytest.mark.parametrize("name", ["state_on", "state_standby"])
def test_state(client, fake, name):
    fake.state_name = name
    r = client.get("/state")
    assert r.status_code == 200
    assert r.json() == fx(name)
    assert_same_shape(r.json(), fx(name))


def test_inputs(client):
    assert_same_shape(client.get("/inputs").json(), fx("inputs"))


@pytest.mark.parametrize("q", ["", "?cached=1", "?cached=true"])
def test_picture(client, q):
    assert_same_shape(client.get("/picture" + q).json(), fx("picture"))


def test_picture_cached_flag_chega_ao_service(fake):
    seen = []

    async def picture(cached=False):
        seen.append(cached)
        return fx("picture")

    fake.picture = picture
    with TestClient(create_app(fake), base_url="http://127.0.0.1:8766") as c:
        c.get("/picture")
        c.get("/picture?cached=1")
    assert seen == [False, True]


def test_key(client):
    r = client.post("/key/power")
    assert r.status_code == 200
    assert_same_shape(r.json(), fx("key"))


def test_key_wol(fake, client):
    async def wol(name):
        return "wol"

    fake.send_key = wol
    assert client.post("/key/power").json() == {"ok": True, "channel": "wol"}


@pytest.mark.parametrize(
    "path,body",
    [
        ("/pair/start", None),
        ("/pair/finish", {"pin": "0000"}),
        ("/app", {"link": "https://www.youtube.com"}),
    ],
)
def test_ok_only(client, path, body):
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code == 200
    assert_same_shape(r.json(), fx("ok"))


def test_set_input(client):
    r = client.post("/input/3")
    assert_same_shape(r.json(), fx("input_set"))
    assert r.json()["active_port"] == 3


def test_picture_mode(client):
    r = client.post("/picture/mode", json={"mode": "Jogo"})
    assert_same_shape(r.json(), fx("picture_mode"))


def test_picture_backlight(client):
    r = client.post("/picture/backlight", json={"value": 60})
    assert_same_shape(r.json(), fx("picture_backlight"))
    assert r.json()["backlight"] == 60


ERRORS = [
    (errors.NotPaired, "not_paired", 409),
    (errors.AdbUnauthorized, "adb_unauthorized", 409),
    (errors.TVUnreachable, "tv_unreachable", 503),
    (errors.NotSupported, "not_supported", 501),
    (errors.UnknownKey, "unknown_key", 404),
    (errors.TVNotFound, "tv_not_found", 503),
    (errors.InvalidPin, "invalid_pin", 400),
    (errors.UnknownMode, "unknown_mode", 400),
    (errors.InvalidValue, "invalid_value", 400),
    (errors.InputNotConfirmed, "input_not_confirmed", 502),
    (errors.NoCache, "no_cache", 404),
    (errors.PictureUnreadable, "picture_unreadable", 502),
]


@pytest.mark.parametrize("cls,code,status", ERRORS)
def test_erros(client, fake, cls, code, status):
    fake.fail = cls("mensagem pt-BR")
    r = client.get("/inputs")
    assert r.status_code == status
    assert r.json() == {"error": code, "message": "mensagem pt-BR"}


def test_erro_internal(client, fake):
    fake.fail = ValueError("x")
    r = client.get("/inputs")
    assert (r.status_code, r.json()["error"]) == (500, "internal")


def test_erro_forbidden(client):
    r = client.get("/health", headers={"origin": "http://x"})
    assert (r.status_code, r.json()["error"]) == (403, "forbidden")


def test_erro_invalid_request(client):
    r = client.post("/picture/backlight", json={"value": "alto"})
    assert (r.status_code, r.json()["error"]) == (422, "invalid_request")
