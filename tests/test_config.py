import os
from icloud_sync.config import Config


def test_config_load_minimal(monkeypatch, tmp_path):
    monkeypatch.setenv("ICLOUD_USERNAME", "user@test")
    # optional password omitted
    monkeypatch.setenv("LOCAL_DIRECTORY", str(tmp_path))
    cfg = Config.load()
    assert cfg.icloud_username == "user@test"
    assert cfg.sync_interval >= 5
    assert os.path.isdir(cfg.local_directory)


def test_invalid_interval(monkeypatch):
    monkeypatch.setenv("ICLOUD_USERNAME", "user@test")
    monkeypatch.setenv("SYNC_INTERVAL", "abc")
    try:
        Config.load()
    except ValueError as e:
        assert "Invalid SYNC_INTERVAL" in str(e)
    else:
        assert False, "Expected ValueError"


def test_log_json_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ICLOUD_USERNAME", "user@test")
    monkeypatch.setenv("LOCAL_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("LOG_JSON", "1")
    cfg = Config.load()
    assert cfg.log_json is True
