import pytest

from samsung_sidecar import discovery
from samsung_sidecar.discovery import (
    SEARCH_TARGET,
    TVCandidate,
    discover,
    find_tv,
    msearch_message,
    parse_ssdp,
)
from samsung_sidecar.errors import TVNotFound, TVUnreachable

RESPONSE = (
    "HTTP/1.1 200 OK\r\n"
    "CACHE-CONTROL: max-age=1800\r\n"
    "LOCATION: http://10.0.0.5:7676/rcr/\r\n"
    f"ST: {SEARCH_TARGET}\r\n"
    f"USN: uuid:abc::{SEARCH_TARGET}\r\n\r\n"
).encode()


def test_msearch_message():
    msg = msearch_message(3.0).decode()
    assert msg.startswith("M-SEARCH * HTTP/1.1\r\n")
    assert "HOST: 239.255.255.250:1900\r\n" in msg
    assert 'MAN: "ssdp:discover"\r\n' in msg
    assert f"ST: {SEARCH_TARGET}\r\n" in msg
    assert msg.endswith("\r\n\r\n")


def test_parse_ssdp_headers_and_garbage():
    headers = parse_ssdp(RESPONSE)
    assert headers["st"] == SEARCH_TARGET
    assert headers["location"] == "http://10.0.0.5:7676/rcr/"
    assert parse_ssdp(b"\xff\xfe garbage") is None
    assert parse_ssdp(b"NOTIFY * HTTP/1.1\r\n\r\n") is None


def test_collector_keeps_only_samsung_receivers_dedup():
    col = discovery._Collector()
    col.datagram_received(RESPONSE, ("10.0.0.5", 1900))
    col.datagram_received(RESPONSE, ("10.0.0.5", 1900))
    other = RESPONSE.replace(SEARCH_TARGET.encode(), b"urn:other:device:x:1")
    col.datagram_received(other, ("10.0.0.9", 1900))
    col.datagram_received(b"junk", ("10.0.0.8", 1900))
    assert col.hosts == ["10.0.0.5"]


async def test_discover_confirms_with_probe():
    async def ssdp(timeout):
        assert timeout == 1.5
        return ["10.0.0.5", "10.0.0.6", "10.0.0.7"]

    async def probe(host):
        if host == "10.0.0.6":
            return None
        if host == "10.0.0.7":
            raise TVUnreachable("x")
        return TVCandidate(host, "[TV] Frame")

    assert await discover(1.5, ssdp=ssdp, probe=probe) == [TVCandidate("10.0.0.5", "[TV] Frame")]


async def test_discover_matches_mac():
    cands = [TVCandidate("10.0.0.5", "A"), TVCandidate("10.0.0.6", "B")]
    macs = {"10.0.0.5": "aa:aa:aa:aa:aa:aa", "10.0.0.6": "bb:bb:bb:bb:bb:bb"}

    async def disc():
        return cands

    async def get_mac(host):
        return macs[host]

    cand, mac = await find_tv("BB-BB-BB-BB-BB-BB", get_mac, discover=disc)
    assert cand == cands[1] and mac == "bb:bb:bb:bb:bb:bb"


async def test_find_tv_none_returns_first_and_skips_failures():
    cands = [TVCandidate("10.0.0.4", "X"), TVCandidate("10.0.0.5", "A")]

    async def disc():
        return cands

    async def get_mac(host):
        if host == "10.0.0.4":
            raise TVUnreachable("x")
        return "aa:aa:aa:aa:aa:aa"

    assert await find_tv(None, get_mac, discover=disc) == (cands[1], "aa:aa:aa:aa:aa:aa")


async def test_find_tv_not_found():
    async def disc():
        return [TVCandidate("10.0.0.5", "A")]

    async def get_mac(host):
        return "aa:aa:aa:aa:aa:aa"

    with pytest.raises(TVNotFound):
        await find_tv("bb:bb:bb:bb:bb:bb", get_mac, discover=disc)

    async def empty():
        return []

    with pytest.raises(TVNotFound):
        await find_tv(None, get_mac, discover=empty)


async def test_probe_rest_uses_device_name_or_none():
    from fakes import FakeRest, FakeRestFactory

    rf = FakeRestFactory(FakeRest({"device": {"name": "[TV] Samsung Frame"}}))
    assert await discovery.probe_rest("10.0.0.5", rest_factory=rf) == TVCandidate(
        "10.0.0.5", "[TV] Samsung Frame"
    )
    assert rf.hosts == ["10.0.0.5"]
    down = FakeRestFactory(FakeRest(error=OSError("refused")))
    assert await discovery.probe_rest("10.0.0.6", rest_factory=down) is None
