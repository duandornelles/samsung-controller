import asyncio
import time

import pytest
from samsungtvws.exceptions import HttpApiError, UnauthorizedError
from websockets.exceptions import ConnectionClosedError

from samsung_sidecar.channels.local import LocalChannel, default_rest_factory, default_ws_factory
from samsung_sidecar.errors import AdbUnauthorized, TVUnreachable

from fakes import FakeRest, FakeRestFactory, FakeWsFactory


def make(token="tok", rest=None, ws=None, **kw):
    tokens: list[str] = []
    rest_factory = FakeRestFactory(rest or FakeRest())
    ws_factory = ws or FakeWsFactory()
    ch = LocalChannel(
        "10.0.0.5", token, tokens.append, rest_factory=rest_factory, ws_factory=ws_factory, **kw
    )
    return ch, rest_factory, ws_factory, tokens


async def test_device_info_returns_device_dict():
    ch, rf, _, _ = make(rest=FakeRest({"device": {"name": "Frame"}, "id": "x"}))
    assert await ch.device_info() == {"name": "Frame"}
    assert rf.hosts == ["10.0.0.5"]


@pytest.mark.parametrize("err", [HttpApiError("x"), TimeoutError(), OSError("refused")])
async def test_device_info_unreachable(err):
    ch, *_ = make(rest=FakeRest(error=err))
    with pytest.raises(TVUnreachable):
        await ch.device_info()


async def test_power_state_on_and_standby():
    ch, *_ = make(rest=FakeRest({"device": {"PowerState": "on"}}))
    assert await ch.power_state() == "on"
    ch, *_ = make(rest=FakeRest({"device": {"PowerState": "standby"}}))
    assert await ch.power_state() == "standby"
    ch, *_ = make(rest=FakeRest(error=HttpApiError("down")))
    assert await ch.power_state() is None


async def test_mac_lowercase():
    ch, *_ = make(rest=FakeRest({"device": {"wifiMac": "AA:BB:CC:DD:EE:FF"}}))
    assert await ch.mac() == "aa:bb:cc:dd:ee:ff"
    ch, *_ = make(rest=FakeRest({"device": {}}))
    assert await ch.mac() is None


async def test_key_sends_click():
    ch, _, ws, _ = make()
    assert not ch.connected
    await ch.key("KEY_HOME")
    assert ws.remote_cmds() == [("Click", "KEY_HOME")]
    assert ch.connected
    assert ws.created[0].host == "10.0.0.5" and ws.created[0].token == "tok"


async def test_hold_press_wait_release():
    sleeps: list[float] = []
    ws = FakeWsFactory()

    async def fake_sleep(s):
        sleeps.append(s)
        ws.sent.append({"method": "sleep", "params": {}})

    ch, *_ = make(ws=ws, sleep=fake_sleep)
    await ch.hold("KEY_POWER", 3)
    assert sleeps == [3]
    assert [c["method"] for c in ws.sent] == ["ms.remote.control", "sleep", "ms.remote.control"]
    assert ws.remote_cmds() == [("Press", "KEY_POWER"), ("Release", "KEY_POWER")]


async def test_first_connect_without_token_saves_token():
    ch, _, ws, tokens = make(token=None, ws=FakeWsFactory(issue_token="abc"))
    await ch.key("KEY_HOME")
    assert tokens == ["abc"]
    assert not ch.pairing_pending
    assert ws.remote_cmds() == [("Click", "KEY_HOME")]
    # Reconexão posterior usa o token recebido e não chama on_token de novo.
    await ch.set_host("10.0.0.6")
    await ch.key("KEY_HOME")
    assert ws.created[-1].token == "abc" and ws.created[-1].host == "10.0.0.6"
    assert tokens == ["abc"]


async def test_pairing_pending_visible_while_waiting():
    ws = FakeWsFactory(issue_token="abc")
    ws.block_open = True
    ch, _, _, tokens = make(token=None, ws=ws)
    assert not ch.pairing_pending
    task = asyncio.create_task(ch.key("KEY_HOME"))
    await ws.open_started.wait()
    assert ch.pairing_pending
    ws.block_open = False
    # Destrava: substitui a espera por uma conexão que conclui.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not ch.pairing_pending
    await ch.key("KEY_HOME")
    assert tokens == ["abc"] and not ch.pairing_pending


async def test_pairing_pending_true_until_token_arrives():
    ws = FakeWsFactory(issue_token="abc")
    ws.open_delay = 0.05
    ch, _, _, tokens = make(token=None, ws=ws)
    task = asyncio.create_task(ch.key("KEY_HOME"))
    await ws.open_started.wait()
    assert ch.pairing_pending and tokens == []
    await task
    assert not ch.pairing_pending and tokens == ["abc"]


async def test_pairing_timeout_unauthorized():
    ws = FakeWsFactory()
    ws.block_open = True
    ch, _, _, tokens = make(token=None, ws=ws, pairing_timeout_s=0.2)
    start = time.monotonic()
    with pytest.raises(AdbUnauthorized) as ei:
        await ch.key("KEY_HOME")
    assert time.monotonic() - start < 1
    assert ei.value.message == "Aceite o pedido de conexão na TV"
    assert not ch.pairing_pending and not ch.connected and tokens == []
    assert ws.created[0].closed


async def test_with_token_no_pairing_pending_and_connect_timeout_unreachable():
    ws = FakeWsFactory()
    ws.block_open = True
    ch, *_ = make(ws=ws, connect_timeout_s=0.1)
    task = asyncio.create_task(ch.key("KEY_HOME"))
    await ws.open_started.wait()
    assert not ch.pairing_pending
    with pytest.raises(TVUnreachable):
        await task


async def test_tokenless_tcp_timeout_is_unreachable():
    ws = FakeWsFactory()
    ws.open_errors = [TimeoutError("timed out during opening handshake")]
    ch, *_ = make(token=None, ws=ws)
    with pytest.raises(TVUnreachable):
        await ch.key("KEY_HOME")
    assert not ch.pairing_pending


async def test_unauthorized_event():
    ws = FakeWsFactory()
    ws.open_errors = [UnauthorizedError({"event": "ms.channel.unauthorized"})]
    ch, *_ = make(token=None, ws=ws)
    with pytest.raises(AdbUnauthorized):
        await ch.key("KEY_HOME")
    assert not ch.pairing_pending and not ch.connected


async def test_unreachable():
    ws = FakeWsFactory()
    ws.open_errors = [ConnectionRefusedError("refused")]
    ch, *_ = make(ws=ws)
    with pytest.raises(TVUnreachable):
        await ch.key("KEY_HOME")
    assert not ch.connected


async def test_concurrent_keys_single_connection():
    ws = FakeWsFactory()
    ws.open_delay = 0.01
    ch, *_ = make(ws=ws)
    await asyncio.gather(*(ch.key(f"KEY_{i}") for i in range(5)))
    assert ws.open_calls == 1 and len(ws.created) == 1
    assert sorted(k for _, k in ws.remote_cmds()) == [f"KEY_{i}" for i in range(5)]


async def test_reconnects_once_when_socket_dropped():
    ws = FakeWsFactory()
    ch, *_ = make(ws=ws)
    await ch.key("KEY_HOME")
    ws.send_errors = [ConnectionClosedError(None, None)]
    await ch.key("KEY_MENU")
    assert len(ws.created) == 2 and ws.created[0].closed
    assert ws.remote_cmds() == [("Click", "KEY_HOME"), ("Click", "KEY_MENU")]


async def test_send_fails_twice_unreachable():
    ws = FakeWsFactory()
    ch, *_ = make(ws=ws)
    await ch.key("KEY_HOME")
    ws.send_errors = [ConnectionClosedError(None, None), OSError("broken")]
    with pytest.raises(TVUnreachable):
        await ch.key("KEY_MENU")
    assert not ch.connected


async def test_run_app_and_browser():
    ch, _, ws, _ = make()
    await ch.run_app("111299001912")
    await ch.open_browser("https://example.com")
    assert [c["method"] for c in ws.sent] == ["ms.channel.emit", "ms.channel.emit"]
    app, browser = (c["params"] for c in ws.sent)
    assert app["event"] == "ed.apps.launch"
    assert app["data"]["appId"] == "111299001912" and app["data"]["action_type"] == "DEEP_LINK"
    assert browser["data"] == {
        "action_type": "NATIVE_LAUNCH",
        "appId": "org.tizen.browser",
        "metaTag": "https://example.com",
    }


async def test_set_host_and_close_drop_connection():
    ch, _, ws, _ = make()
    await ch.key("KEY_HOME")
    await ch.set_host("10.0.0.9")
    assert ws.created[0].closed and not ch.connected
    await ch.key("KEY_HOME")
    assert ws.created[1].host == "10.0.0.9"
    await ch.close()
    assert ws.created[1].closed and not ch.connected


def test_default_ws_factory_url():
    remote = default_ws_factory("10.0.0.5", "tok", 4.0)
    assert remote._format_websocket_url(remote.endpoint) == (
        "wss://10.0.0.5:8002/api/v2/channels/samsung.remote.control"
        "?name=U2Ftc3VuZyBDb250cm9sbGVy&token=tok"
    )
    assert remote.timeout == 4.0 and remote.key_press_delay == 0


def test_default_ws_factory_url_without_token():
    remote = default_ws_factory("10.0.0.5", None, 4.0)
    assert "token=" not in remote._format_websocket_url(remote.endpoint)


def test_default_rest_factory_url():
    rest = default_rest_factory("10.0.0.5", 4.0)
    assert rest.url == "http://10.0.0.5:8001/api/v2/"
