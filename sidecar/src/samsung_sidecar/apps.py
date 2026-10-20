"""Link de app -> id de aplicativo Tizen."""

APP_IDS: dict[str, str] = {
    "https://www.youtube.com": "111299001912",
    "https://www.netflix.com": "3201907018807",
    "https://www.primevideo.com": "3201910019365",
    "https://www.disneyplus.com": "3201901017640",
    "https://www.globoplay.globo.com": "3201908019041",
}


def _normalize(link: str) -> str:
    s = link.strip().lower()
    for scheme in ("https://", "http://"):
        if s.startswith(scheme):
            s = s[len(scheme):]
            break
    s = s.removeprefix("www.")
    return s.rstrip("/")


_BY_HOST = {_normalize(k): v for k, v in APP_IDS.items()}


def app_for(link: str) -> str | None:
    return _BY_HOST.get(_normalize(link))
