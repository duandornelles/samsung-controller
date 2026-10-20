"""CLI de teste `samsung` que conversa com a API local do sidecar."""

import argparse
import asyncio
import json
import os
import sys

import httpx

from .channels.smartthings import SmartThingsChannel
from .config import load_config, save_config
from .errors import TVError
from .keys import KEYS

DEFAULT_URL = "http://127.0.0.1:8766"
TIMEOUT = 30.0
HINT_DOWN = "Sidecar não está rodando. Inicie com: uv run samsung-sidecar"
HINT_PAIR = "Aceite o pedido de conexão ('Permitir') na tela da TV"


class _ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="samsung", description="Controle da TV Samsung via sidecar")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="saúde do sidecar")
    sub.add_parser("state", help="estado da TV")
    sub.add_parser("pair", help="pareia com a TV (aceite 'Permitir' na TV)")
    k = sub.add_parser("key", help="envia uma tecla do controle")
    k.add_argument("name", metavar="nome", choices=sorted(KEYS), help="tecla: " + ", ".join(KEYS))
    a = sub.add_parser("app", help="abre um app por link")
    a.add_argument("link")
    sub.add_parser("inputs", help="lista as entradas HDMI")
    i = sub.add_parser("input", help="troca a entrada HDMI")
    i.add_argument("port", type=int, metavar="porta")
    sub.add_parser("picture", help="lê o modo de imagem e o brilho")
    m = sub.add_parser("mode", help="troca o modo de imagem")
    m.add_argument("label", metavar="rótulo")
    s = sub.add_parser("smartthings", help="salva o token SmartThings e escolhe a TV")
    s.add_argument("token")
    return p


def _call(client: httpx.Client, method: str, path: str, **kw) -> dict:
    resp = client.request(method, path, **kw)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        raise _ApiError(
            str(data.get("error", resp.status_code)) if isinstance(data, dict) else str(resp.status_code),
            str(data.get("message", resp.text)) if isinstance(data, dict) else resp.text,
        )
    return data


def _show(data: dict | list) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if isinstance(data, dict) and data.get("adb_auth") == "pending":
        print(HINT_PAIR, file=sys.stderr)


def _name(dev: dict) -> str:
    return str(dev.get("label") or dev.get("name") or dev.get("deviceId", ""))


def _is_tv(dev: dict) -> bool:
    name = _name(dev).casefold()
    return "frame" in name or "tv" in name


def _smartthings(token: str, transport: httpx.AsyncBaseTransport | None) -> None:
    """Grava st_token/st_device_id direto no config (sem HTTP, sem imprimir o token)."""
    try:
        devices = asyncio.run(SmartThingsChannel.list_devices(token, transport=transport))
    except TVError as e:
        raise _ApiError(e.code, e.message) from None
    tvs = [d for d in devices if _is_tv(d) and d.get("deviceId")]
    if not tvs:
        raise _ApiError("not_found", "Nenhuma TV (nome com 'Frame' ou 'TV') encontrada no SmartThings")
    chosen = tvs[0]
    if len(tvs) > 1:
        for n, d in enumerate(tvs):
            print(f"{n}: {_name(d)}")
        try:
            chosen = tvs[int(input("Índice da TV: ").strip())]
        except (ValueError, IndexError):
            raise _ApiError("invalid_choice", "Índice inválido") from None
    cfg = load_config()
    cfg.st_token = token
    cfg.st_device_id = str(chosen["deviceId"])
    save_config(cfg)
    print(f"SmartThings configurado: {_name(chosen)}")


def _run(args: argparse.Namespace, client: httpx.Client) -> None:
    c = args.cmd
    if c == "health":
        _show(_call(client, "GET", "/health"))
    elif c == "state":
        _show(_call(client, "GET", "/state"))
    elif c == "key":
        _show(_call(client, "POST", f"/key/{args.name}"))
    elif c == "app":
        _show(_call(client, "POST", "/app", json={"link": args.link}))
    elif c == "inputs":
        _show(_call(client, "GET", "/inputs"))
    elif c == "input":
        _show(_call(client, "POST", f"/input/{args.port}"))
    elif c == "picture":
        _show(_call(client, "GET", "/picture"))
    elif c == "mode":
        _show(_call(client, "POST", "/picture/mode", json={"mode": args.label}))
    elif c == "pair":
        print(HINT_PAIR, file=sys.stderr)
        _call(client, "POST", "/pair/start")
        # A Samsung não usa PIN; o sidecar aceita qualquer valor em /pair/finish.
        _show(_call(client, "POST", "/pair/finish", json={"pin": "0000"}))


def main(
    argv: list[str] | None = None,
    client: httpx.Client | None = None,
    st_transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    own = client is None and args.cmd != "smartthings"
    if own:
        client = httpx.Client(
            base_url=os.environ.get("SAMSUNG_SIDECAR_URL", DEFAULT_URL), timeout=TIMEOUT
        )
    try:
        if args.cmd == "smartthings":
            _smartthings(args.token, st_transport)
        else:
            _run(args, client)
        return 0
    except _ApiError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return 1
    except httpx.ConnectError:
        print(HINT_DOWN, file=sys.stderr)
        return 1
    finally:
        if own:
            client.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
