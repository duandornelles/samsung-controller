"""API HTTP local (FastAPI) na frente do TVService: contrato em docs/CONTRATO-API.md."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .channels.local import LocalChannel
from .channels.smartthings import SmartThingsChannel
from .config import load_config
from .errors import TVError
from .service import TVService

log = logging.getLogger(__name__)

PORT = 8766
DEFAULT_ALLOWED_HOSTS = frozenset({f"127.0.0.1:{PORT}", f"localhost:{PORT}"})


class PinBody(BaseModel):
    pin: str


class LinkBody(BaseModel):
    link: str


class ModeBody(BaseModel):
    mode: str


class BacklightBody(BaseModel):
    value: int


def create_app(
    service: TVService, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS
) -> FastAPI:
    hosts = frozenset(allowed_hosts)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        warm = asyncio.create_task(service.warmup())
        try:
            yield
        finally:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
            await service.close()

    app = FastAPI(title="Samsung Sidecar", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # CSRF / DNS rebinding: browsers send Origin on cross-site POSTs and
        # the rebound name in Host; the CLI (httpx) sends no Origin.
        if "origin" in request.headers or request.headers.get("host") not in hosts:
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "message": "Origem não permitida"},
            )
        return await call_next(request)

    @app.exception_handler(TVError)
    async def tv_error_handler(_: Request, exc: TVError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": str(exc)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_request", "message": f"Requisição inválida: {details}"},
        )

    @app.exception_handler(Exception)
    async def internal_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error("erro interno em %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal", "message": "Erro interno no sidecar"},
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return await service.health()

    @app.get("/state")
    async def state() -> dict[str, Any]:
        return await service.state()

    @app.post("/pair/start")
    async def pair_start() -> dict[str, bool]:
        await service.start_pairing()
        return {"ok": True}

    @app.post("/pair/finish")
    async def pair_finish(body: PinBody) -> dict[str, bool]:
        await service.finish_pairing(body.pin)
        return {"ok": True}

    @app.post("/key/{name}")
    async def key(name: str) -> dict[str, Any]:
        return {"ok": True, "channel": await service.send_key(name)}

    @app.post("/app")
    async def launch_app(body: LinkBody) -> dict[str, bool]:
        await service.launch_app(body.link)
        return {"ok": True}

    @app.get("/inputs")
    async def inputs() -> list[dict[str, Any]]:
        return await service.inputs()

    @app.post("/input/{port}")
    async def set_input(port: int) -> dict[str, Any]:
        return await service.set_input(port)

    @app.get("/picture")
    async def picture(cached: bool = False) -> dict[str, Any]:
        return await service.picture(cached=cached)

    @app.post("/picture/mode")
    async def picture_mode(body: ModeBody) -> dict[str, Any]:
        return await service.set_picture_mode(body.mode)

    @app.post("/picture/backlight")
    async def picture_backlight(body: BacklightBody) -> dict[str, Any]:
        return await service.set_backlight(body.value)

    return app


def build_service() -> TVService:
    def local_factory(host: str, token: str | None, on_token: Callable[[str], None]) -> LocalChannel:
        return LocalChannel(host, token, on_token)

    def st_factory(token: str, device_id: str) -> SmartThingsChannel:
        return SmartThingsChannel(token, device_id)

    return TVService(load_config(), local_factory, st_factory)


def main() -> None:
    uvicorn.run(create_app(build_service()), host="127.0.0.1", port=PORT)
