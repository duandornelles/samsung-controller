import json
from pathlib import Path

import httpx
import pytest

from samsung_sidecar.channels.smartthings import SmartThingsChannel, picture_label
from samsung_sidecar.errors import NotSupported, TVUnreachable

FIX = Path(__file__).parent / "fixtures"
STATUS = json.loads((FIX / "smartthings_status.json").read_text())
DEVICE = json.loads((FIX / "smartthings_device.json").read_text())
TOKEN = "secret-token-123"


def make(handler=None, status=None, device=None):
    requests: list[httpx.Request] = []

    def default(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        path = req.url.path
        if path.endswith("/status"):
            return httpx.Response(200, json=status or STATUS)
        if path.endswith("/commands"):
            return httpx.Response(200, json={"results": [{"status": "ACCEPTED"}]})
        if path == "/v1/devices":
            return httpx.Response(200, json={"items": [DEVICE]})
        return httpx.Response(200, json=device or DEVICE)

    def wrapped(req):
        if handler:
            requests.append(req)
            return handler(req)
        return default(req)

    ch = SmartThingsChannel(TOKEN, "dev-1", transport=httpx.MockTransport(wrapped))
    return ch, requests


async def test_input_sources():
    ch, _ = make()
    assert await ch.input_sources() == (["digitalTv", "HDMI1", "HDMI2"], "HDMI1")


async def test_input_sources_samsungvd_fallback():
    st = json.loads(json.dumps(STATUS))
    main = st["components"]["main"]
    main["samsungvd.mediaInputSource"] = main.pop("mediaInputSource")
    ch, reqs = make(status=st)
    assert await ch.input_sources() == (["digitalTv", "HDMI1", "HDMI2"], "HDMI1")
    await ch.set_input("HDMI2")
    body = json.loads(reqs[-1].content)
    assert body["commands"][0]["capability"] == "samsungvd.mediaInputSource"


async def test_set_input_command_body():
    ch, reqs = make()
    await ch.set_input("HDMI2")
    req = reqs[-1]
    assert req.method == "POST" and req.url.path == "/v1/devices/dev-1/commands"
    assert json.loads(req.content) == {
        "commands": [
            {
                "component": "main",
                "capability": "mediaInputSource",
                "command": "setInputSource",
                "arguments": ["HDMI2"],
            }
        ]
    }


async def test_picture_modes_and_labels():
    ch, reqs = make()
    assert await ch.picture_modes() == (["Dynamic", "Standard", "Natural", "Movie"], "Standard")
    assert picture_label("Standard") == "Padrão"
    assert picture_label("Dynamic") == "Dinâmico"
    assert picture_label("FILMMAKER MODE") == "Filmmaker"
    assert picture_label("X") == "X"
    await ch.set_picture_mode("Movie")
    assert json.loads(reqs[-1].content)["commands"][0] == {
        "component": "main",
        "capability": "custom.picturemode",
        "command": "setPictureMode",
        "arguments": ["Movie"],
    }


async def test_volume():
    ch, _ = make()
    assert await ch.volume() == {"level": 12, "max": 100, "muted": False}


async def test_volume_absent():
    ch, _ = make(status={"components": {"main": {}}})
    assert await ch.volume() is None


async def test_backlight_absent():
    ch, _ = make()
    assert await ch.backlight() is None
    with pytest.raises(NotSupported, match="Brilho não disponível nesta TV"):
        await ch.set_backlight(50)


async def test_backlight_present_generic():
    dev = json.loads(json.dumps(DEVICE))
    dev["components"][0]["capabilities"].append({"id": "custom.brightnessLevel", "version": 1})
    st = json.loads(json.dumps(STATUS))
    st["components"]["main"]["custom.brightnessLevel"] = {"level": {"value": 40}}
    ch, reqs = make(status=st, device=dev)
    assert await ch.backlight() == 40
    await ch.set_backlight(70)
    assert json.loads(reqs[-1].content)["commands"][0] == {
        "component": "main",
        "capability": "custom.brightnessLevel",
        "command": "setLevel",
        "arguments": [70],
    }


async def test_unauthorized():
    ch, _ = make(handler=lambda r: httpx.Response(401, json={}))
    with pytest.raises(NotSupported, match="Token SmartThings inválido"):
        await ch.status()
    with pytest.raises(NotSupported):
        await ch.set_input("HDMI1")
    with pytest.raises(NotSupported):
        await SmartThingsChannel.list_devices(
            TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(401))
        )


async def test_network_error_is_unreachable():
    def boom(req):
        raise httpx.ConnectTimeout("t", request=req)

    ch, _ = make(handler=boom)
    with pytest.raises(TVUnreachable, match="SmartThings inacessível"):
        await ch.status()


async def test_server_error_is_unreachable():
    ch, _ = make(handler=lambda r: httpx.Response(500))
    with pytest.raises(TVUnreachable):
        await ch.status()


async def test_auth_header_and_no_token_in_errors():
    ch, reqs = make()
    await ch.status()
    assert reqs[-1].headers["Authorization"] == f"Bearer {TOKEN}"

    def boom(req):
        raise httpx.ConnectError(f"fail {req.headers['Authorization']}", request=req)

    ch2, _ = make(handler=boom)
    with pytest.raises(TVUnreachable) as ei:
        await ch2.status()
    assert TOKEN not in str(ei.value) and TOKEN not in repr(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__

    ch3, _ = make(handler=lambda r: httpx.Response(401))
    with pytest.raises(NotSupported) as ei:
        await ch3.status()
    assert TOKEN not in str(ei.value)


async def test_list_devices():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"items": [DEVICE]}))
    assert await SmartThingsChannel.list_devices(TOKEN, transport=t) == [DEVICE]
