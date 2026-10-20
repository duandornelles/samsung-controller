"""Middleware, validação e handlers globais da API."""

import warnings

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*httpx2.*")
    from fastapi.testclient import TestClient

from samsung_sidecar.api import create_app
from samsung_sidecar.errors import NoCache


class FakeService:
    def __init__(self):
        self.closed = False
        self.warmed = False
        self.boom: Exception | None = None

    async def warmup(self):
        self.warmed = True

    async def close(self):
        self.closed = True

    async def health(self):
        if self.boom:
            raise self.boom
        return {"ok": True}

    async def picture(self, cached=False):
        raise NoCache("sem cache")

    async def set_input(self, port):
        return {"ok": True, "active_port": port}

    async def set_backlight(self, value):
        return {"ok": True, "backlight": value}


@pytest.fixture
def svc():
    return FakeService()


@pytest.fixture
def client(svc):
    with TestClient(
        create_app(svc), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    ) as c:
        yield c


def test_port_8766_ok(client):
    assert client.get("/health").json() == {"ok": True}


def test_localhost_host_ok(client):
    assert client.get("/health", headers={"host": "localhost:8766"}).status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "evil.com", "127.0.0.1"])
def test_host_errado_403(client, host):
    r = client.get("/health", headers={"host": host})
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden", "message": "Origem não permitida"}


def test_qualquer_origin_403(client):
    r = client.get("/health", headers={"origin": "http://127.0.0.1:8766"})
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_422_shape(client):
    r = client.post("/input/abc")
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "invalid_request"
    assert body["message"].startswith("Requisição inválida: ")


def test_422_sem_pin(client):
    assert client.post("/pair/finish", json={}).status_code == 422


def test_500_shape(client, svc):
    svc.boom = RuntimeError("segredo")
    r = client.get("/health")
    assert r.status_code == 500
    assert r.json() == {"error": "internal", "message": "Erro interno no sidecar"}


def test_tverror_mapeado(client):
    r = client.get("/picture")
    assert (r.status_code, r.json()["error"]) == (404, "no_cache")


def test_lifespan(svc):
    with TestClient(create_app(svc), base_url="http://127.0.0.1:8766"):
        pass
    assert svc.closed


def test_allowed_hosts_custom(svc):
    with TestClient(create_app(svc, {"x:1"}), base_url="http://x:1") as c:
        assert c.get("/health").status_code == 200
