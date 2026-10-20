"""Nome de tecla do contrato -> KEY_* Samsung."""

from .errors import UnknownKey

KEYS: dict[str, str] = {
    "power": "KEY_POWER",
    "home": "KEY_HOME",
    "back": "KEY_RETURN",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "ok": "KEY_ENTER",
    "volume_up": "KEY_VOLUP",
    "volume_down": "KEY_VOLDOWN",
    "mute": "KEY_MUTE",
    "play_pause": "KEY_PLAY_BACK",
    "menu": "KEY_MENU",
    "settings": "KEY_MENU",
}


def samsung_key(name: str) -> str:
    try:
        return KEYS[name]
    except KeyError:
        raise UnknownKey(f"Tecla desconhecida: {name}") from None
