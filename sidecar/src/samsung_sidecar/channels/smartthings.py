"""Canal SmartThings (REST, httpx): entrada, modo de imagem, volume e brilho.

O token nunca aparece em exceções nem em logs: erros de rede são convertidos
em ``TVUnreachable`` sem encadear a exceção original (``from None``).
"""

from typing import Any

import httpx

from samsung_sidecar.errors import NotSupported, TVUnreachable

BASE_URL = "https://api.smartthings.com/v1"
COMPONENT = "main"
INPUT_CAPABILITIES = ("mediaInputSource", "samsungvd.mediaInputSource")
PICTURE_CAPABILITY = "custom.picturemode"

PICTURE_LABELS: dict[str, str] = {
    "Dynamic": "Dinâmico",
    "Standard": "Padrão",
    "Natural": "Natural",
    "Movie": "Filme",
    "FILMMAKER MODE": "Filmmaker",
}

_UNAUTHORIZED_MSG = "Token SmartThings inválido"
_FORBIDDEN_MSG = "Token SmartThings sem permissão ou inválido"
_NOT_FOUND_MSG = "Dispositivo SmartThings não encontrado"
_UNREACHABLE_MSG = "SmartThings inacessível"
NO_BACKLIGHT_MSG = "Brilho não disponível nesta TV"


def picture_label(value: str) -> str:
    return PICTURE_LABELS.get(value, value)


def _check(resp: httpx.Response) -> httpx.Response:
    code = resp.status_code
    if code < 400:
        return resp
    if code == 401:
        raise NotSupported(_UNAUTHORIZED_MSG)
    if code == 403:
        raise NotSupported(_FORBIDDEN_MSG)
    if code == 404:
        raise NotSupported(_NOT_FOUND_MSG)
    if code in (408, 429) or code >= 500:
        raise TVUnreachable(_UNREACHABLE_MSG)
    raise NotSupported(f"SmartThings recusou o comando (HTTP {code})")


async def _request(
    client_kwargs: dict[str, Any], method: str, url: str, **kw: Any
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.request(method, url, **kw)
    except httpx.HTTPError:
        raise TVUnreachable(_UNREACHABLE_MSG) from None
    return _check(resp)


def _value(cap: dict[str, Any], attr: str) -> Any:
    entry = cap.get(attr)
    return entry.get("value") if isinstance(entry, dict) else None


class SmartThingsChannel:
    def __init__(
        self,
        token: str,
        device_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
        timeout_s: float = 10.0,
    ) -> None:
        self._device_id = device_id
        self._base = base_url.rstrip("/")
        self._kwargs: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {token}"},
            "timeout": timeout_s,
            "transport": transport,
        }
        self._brightness_cap: str | None | bool = False  # False = não descoberto

    def __repr__(self) -> str:
        return f"SmartThingsChannel(device_id={self._device_id!r})"

    @property
    def _dev(self) -> str:
        return f"{self._base}/devices/{self._device_id}"

    async def status(self) -> dict:
        resp = await _request(self._kwargs, "GET", f"{self._dev}/status")
        return resp.json()

    async def command(self, capability: str, command: str, args: list) -> None:
        body = {
            "commands": [
                {
                    "component": COMPONENT,
                    "capability": capability,
                    "command": command,
                    "arguments": args,
                }
            ]
        }
        await _request(self._kwargs, "POST", f"{self._dev}/commands", json=body)

    @staticmethod
    def _main(status: dict) -> dict[str, Any]:
        return status.get("components", {}).get(COMPONENT, {})

    @staticmethod
    def _input_cap(main: dict[str, Any]) -> str:
        # Algumas Samsung expõem a entrada como samsungvd.mediaInputSource.
        for cap in INPUT_CAPABILITIES:
            if cap in main:
                return cap
        return INPUT_CAPABILITIES[0]

    async def input_sources(self) -> tuple[list[str], str | None]:
        main = self._main(await self.status())
        cap = main.get(self._input_cap(main), {})
        return list(_value(cap, "supportedInputSources") or []), _value(cap, "inputSource")

    async def set_input(self, source: str) -> None:
        main = self._main(await self.status())
        await self.command(self._input_cap(main), "setInputSource", [source])

    async def picture_modes(self) -> tuple[list[str], str | None]:
        cap = self._main(await self.status()).get(PICTURE_CAPABILITY, {})
        return list(_value(cap, "supportedPictureModes") or []), _value(cap, "pictureMode")

    async def set_picture_mode(self, mode: str) -> None:
        await self.command(PICTURE_CAPABILITY, "setPictureMode", [mode])

    async def volume(self) -> dict | None:
        main = self._main(await self.status())
        level = _value(main.get("audioVolume", {}), "volume")
        if level is None:
            return None
        mute = _value(main.get("audioMute", {}), "mute")
        return {"level": int(level), "max": 100, "muted": mute == "muted"}

    async def _find_brightness_cap(self) -> str | None:
        """Descobre em runtime uma capacidade de brilho (id com brightness/backlight).

        Genérico e NÃO verificado em hardware: a SmartThings não tem capacidade
        padrão de brilho para TVs Samsung.
        """
        if self._brightness_cap is False:
            resp = await _request(self._kwargs, "GET", self._dev)
            found: str | None = None
            for comp in resp.json().get("components", []):
                if comp.get("id") != COMPONENT:
                    continue
                for cap in comp.get("capabilities", []):
                    cid = str(cap.get("id", ""))
                    if "brightness" in cid.lower() or "backlight" in cid.lower():
                        found = cid
                        break
            self._brightness_cap = found
        return self._brightness_cap or None

    @staticmethod
    def _numeric_attr(cap: dict[str, Any]) -> tuple[str, int] | None:
        for attr, entry in cap.items():
            v = entry.get("value") if isinstance(entry, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return attr, int(v)
        return None

    async def backlight(self) -> int | None:
        cap_id = await self._find_brightness_cap()
        if cap_id is None:
            return None
        cap = self._main(await self.status()).get(cap_id, {})
        found = self._numeric_attr(cap)
        return found[1] if found else None

    async def set_backlight(self, v: int) -> None:
        cap_id = await self._find_brightness_cap()
        if cap_id is None:
            raise NotSupported(NO_BACKLIGHT_MSG)
        cap = self._main(await self.status()).get(cap_id, {})
        found = self._numeric_attr(cap)
        if found is None:
            raise NotSupported(NO_BACKLIGHT_MSG)
        attr = found[0]
        await self.command(cap_id, f"set{attr[:1].upper()}{attr[1:]}", [v])

    @staticmethod
    async def list_devices(
        token: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {token}"},
            "timeout": 10.0,
            "transport": transport,
        }
        resp = await _request(kwargs, "GET", f"{BASE_URL}/devices")
        return list(resp.json().get("items", []))
