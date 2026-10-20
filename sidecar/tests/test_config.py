import stat

from samsung_sidecar.config import Config, data_dir, load_config, save_config


def test_data_dir_env(home):
    assert data_dir() == home


def test_data_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMSUNG_CONTROLLER_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert data_dir() == tmp_path / "Library" / "Application Support" / "Samsung-controller"


def test_config_roundtrip_and_perms(home):
    cfg = Config(tv_host="1.2.3.4", tv_mac="AA:BB", tv_name="Frame", ws_token="t", st_token="s", st_device_id="d")
    save_config(cfg)
    assert load_config() == cfg
    assert stat.S_IMODE((home / "config.json").stat().st_mode) == 0o600
    assert list(home.glob("*.tmp")) == [] and len(list(home.iterdir())) == 1


def test_config_missing(home):
    assert load_config() == Config()


def test_config_tolerates_garbage(home):
    p = home / "config.json"
    p.write_text('{"x":1,"tv_host":"1.2.3.4"}')
    assert load_config() == Config(tv_host="1.2.3.4")
    p.write_text("{")
    assert load_config() == Config()
    p.write_text("[1]")
    assert load_config() == Config()
