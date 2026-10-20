"""CLI `samsung`: HTTP via MockTransport; `smartthings` grava o config direto."""

import json

import httpx
import pytest

from samsung_sidecar import cli
from samsung_sidecar.config import Config, load_config, save_config

TOKEN = "tok-super-secreto"


def make_client(handler):
    return httpx.Client(base_url="http://127.0.0.1:8766", transport=httpx.MockTransport(handler))


def test_health(capsys):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={"ok": True})

    assert cli.main(["health"], client=make_client(handler)) == 0
    assert seen == [("GET", "/health")]
    assert '"ok": true' in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv,method,path,body",
    [
        (["state"], "GET", "/state", None),
        (["inputs"], "GET", "/inputs", None),
        (["picture"], "GET", "/picture", None),
        (["key", "power"], "POST", "/key/power", None),
        (["input", "3"], "POST", "/input/3", None),
        (["app", "https://youtube.com"], "POST", "/app", {"link": "https://youtube.com"}),
        (["mode", "Jogo"], "POST", "/picture/mode", {"mode": "Jogo"}),
    ],
)
def test_comandos(argv, method, path, body):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"ok": True})

    assert cli.main(argv, client=make_client(handler)) == 0
    assert seen == [(method, path, body)]


def test_pair(monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.url.path, req.content))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("builtins.input", lambda _="": "0000")
    assert cli.main(["pair"], client=make_client(handler)) == 0
    assert [p for p, _ in seen] == ["/pair/start", "/pair/finish"]


def test_erro_api(capsys):
    def handler(req):
        return httpx.Response(409, json={"error": "not_paired", "message": "TV não pareada"})

    assert cli.main(["state"], client=make_client(handler)) == 1
    assert "not_paired: TV não pareada" in capsys.readouterr().err


def test_sidecar_fora(capsys):
    def handler(req):
        raise httpx.ConnectError("x")

    assert cli.main(["health"], client=make_client(handler)) == 1
    assert "samsung-sidecar" in capsys.readouterr().err


DEVICES = {
    "items": [
        {"deviceId": "d-lamp", "label": "Lâmpada"},
        {"deviceId": "d-frame", "label": "The Frame 55"},
    ]
}


def st_transport(items=DEVICES):
    def handler(req):
        assert req.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=items)

    return httpx.MockTransport(handler)


def test_smartthings_grava_config(home, capsys):
    save_config(Config(tv_host="10.0.0.2", ws_token="ws"))
    assert cli.main(["smartthings", TOKEN], st_transport=st_transport()) == 0
    cfg = load_config()
    assert (cfg.st_token, cfg.st_device_id) == (TOKEN, "d-frame")
    assert (cfg.tv_host, cfg.ws_token) == ("10.0.0.2", "ws")  # preserva o resto
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_smartthings_varios_pergunta_indice(home, monkeypatch, capsys):
    items = {
        "items": [
            {"deviceId": "a", "name": "Samsung TV"},
            {"deviceId": "b", "label": "Frame sala"},
            {"deviceId": "c", "label": "Geladeira"},
        ]
    }
    monkeypatch.setattr("builtins.input", lambda _="": "1")
    assert cli.main(["smartthings", TOKEN], st_transport=st_transport(items)) == 0
    assert load_config().st_device_id == "b"
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_smartthings_nenhuma_tv(home, capsys):
    items = {"items": [{"deviceId": "c", "label": "Geladeira"}]}
    assert cli.main(["smartthings", TOKEN], st_transport=st_transport(items)) == 1
    assert load_config().st_token is None
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_smartthings_token_invalido(home, capsys):
    def handler(req):
        return httpx.Response(401, json={})

    assert cli.main(["smartthings", TOKEN], st_transport=httpx.MockTransport(handler)) == 1
    out = capsys.readouterr()
    assert "inválido" in out.err
    assert TOKEN not in out.out + out.err
    assert load_config().st_token is None
