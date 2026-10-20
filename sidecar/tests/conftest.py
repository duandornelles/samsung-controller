import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_CONTROLLER_HOME", str(tmp_path))
    return tmp_path
