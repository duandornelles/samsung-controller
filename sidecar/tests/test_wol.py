import pytest

from samsung_sidecar.channels.wol import magic_packet, send_magic_packet


def test_magic_packet():
    pkt = magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")
    assert pkt[6:] == bytes.fromhex("aabbccddeeff") * 16


def test_magic_packet_dash():
    assert magic_packet("aa-bb-cc-dd-ee-ff") == magic_packet("AA:BB:CC:DD:EE:FF")


@pytest.mark.parametrize("bad", ["zz", "", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:GG", "AA:BB:CC:DD:EE:FF:00"])
def test_magic_packet_invalid(bad):
    with pytest.raises(ValueError):
        magic_packet(bad)


async def test_send_magic_packet_uses_sender():
    calls = []

    async def sender(packet, addr):
        calls.append((packet, addr))

    await send_magic_packet("AA:BB:CC:DD:EE:FF", sender=sender)
    pkt = magic_packet("AA:BB:CC:DD:EE:FF")
    assert calls == [(pkt, ("255.255.255.255", 9)), (pkt, ("255.255.255.255", 7))]


def test_valid_mac():
    from samsung_sidecar.channels.wol import valid_mac

    assert valid_mac("AA:BB:CC:DD:EE:FF") and valid_mac("aa-bb-cc-dd-ee-ff")
    assert not valid_mac("") and not valid_mac("zz") and not valid_mac(None)
