import pytest

from samsung_sidecar.errors import UnknownKey
from samsung_sidecar.keys import KEYS, samsung_key


def test_keys_map():
    assert samsung_key("back") == "KEY_RETURN"
    assert samsung_key("ok") == "KEY_ENTER"
    assert samsung_key("power") == "KEY_POWER"


def test_keys_exact():
    assert KEYS == {
        "power": "KEY_POWER", "home": "KEY_HOME", "back": "KEY_RETURN",
        "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
        "ok": "KEY_ENTER", "volume_up": "KEY_VOLUP", "volume_down": "KEY_VOLDOWN",
        "mute": "KEY_MUTE", "play_pause": "KEY_PLAY_BACK", "menu": "KEY_MENU",
        "settings": "KEY_MENU",
    }


def test_unknown_key():
    with pytest.raises(UnknownKey):
        samsung_key("explodir")
