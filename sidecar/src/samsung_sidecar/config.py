"""Configuração persistida do controle Samsung."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    tv_host: str | None = None
    tv_mac: str | None = None
    tv_name: str | None = None
    ws_token: str | None = None
    st_token: str | None = None
    st_device_id: str | None = None


def data_dir() -> Path:
    """$SAMSUNG_CONTROLLER_HOME ou ~/Library/Application Support/Samsung-controller (criado se faltar)."""
    if env_home := os.getenv("SAMSUNG_CONTROLLER_HOME"):
        path = Path(env_home)
    else:
        path = Path.home() / "Library" / "Application Support" / "Samsung-controller"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> Config:
    """Lê config.json; ausente, inválido ou com chaves desconhecidas nunca levanta."""
    path = data_dir() / "config.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return Config()
    if not isinstance(data, dict):
        return Config()
    known = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in known})


def save_config(cfg: Config) -> None:
    """Grava config.json de forma atômica com permissão 0o600."""
    path = data_dir() / "config.json"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(cfg), f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
