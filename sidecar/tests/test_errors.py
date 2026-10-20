import pytest

from samsung_sidecar import errors

TABLE = {
    "NotPaired": ("not_paired", 409),
    "AdbUnauthorized": ("adb_unauthorized", 409),
    "TVUnreachable": ("tv_unreachable", 503),
    "NotSupported": ("not_supported", 501),
    "UnknownKey": ("unknown_key", 404),
    "TVNotFound": ("tv_not_found", 503),
    "InvalidPin": ("invalid_pin", 400),
    "UnknownMode": ("unknown_mode", 400),
    "InvalidValue": ("invalid_value", 400),
    "InputNotConfirmed": ("input_not_confirmed", 502),
    "NoCache": ("no_cache", 404),
    "PictureUnreadable": ("picture_unreadable", 502),
}


@pytest.mark.parametrize("name", TABLE)
def test_error_table(name):
    exc = getattr(errors, name)("msg")
    assert isinstance(exc, errors.TVError)
    assert (exc.code, exc.http_status) == TABLE[name]
    assert exc.message == "msg" and str(exc) == "msg"


def test_error_codes():
    assert (errors.UnknownMode("x").code, errors.UnknownMode("x").http_status) == ("unknown_mode", 400)
