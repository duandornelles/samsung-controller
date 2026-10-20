"""Erros do sidecar, mapeados para o contrato HTTP {"error","message"}."""


class TVError(Exception):
    """Base dos erros da TV."""

    code: str
    http_status: int

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class NotPaired(TVError):
    code = "not_paired"
    http_status = 409


class AdbUnauthorized(TVError):
    code = "adb_unauthorized"
    http_status = 409


class TVUnreachable(TVError):
    code = "tv_unreachable"
    http_status = 503


class NotSupported(TVError):
    code = "not_supported"
    http_status = 501


class UnknownKey(TVError):
    code = "unknown_key"
    http_status = 404


class TVNotFound(TVError):
    code = "tv_not_found"
    http_status = 503


class InvalidPin(TVError):
    code = "invalid_pin"
    http_status = 400


class UnknownMode(TVError):
    code = "unknown_mode"
    http_status = 400


class InvalidValue(TVError):
    code = "invalid_value"
    http_status = 400


class InputNotConfirmed(TVError):
    code = "input_not_confirmed"
    http_status = 502


class NoCache(TVError):
    code = "no_cache"
    http_status = 404


class PictureUnreadable(TVError):
    code = "picture_unreadable"
    http_status = 502
