from icloud_sync.sync_manager import SyncManager
from icloud_sync.config import Config

class DummyConfig(Config):
    pass

def build_manager(strategy: str) -> SyncManager:
    cfg = Config.load()
    cfg.conflict_strategy = strategy
    cfg.no_remote = True  # disable remote interactions
    return SyncManager(cfg)

def test_conflict_prefer_remote(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME','user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    m = build_manager('prefer_remote')
    assert m._resolve_conflict(100.0, 200.0, 'prefer_remote') == 'download'

def test_conflict_prefer_local(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME','user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    m = build_manager('prefer_local')
    assert m._resolve_conflict(300.0, 100.0, 'prefer_local') == 'skip'

def test_conflict_keep_both(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME','user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    m = build_manager('keep_both')
    assert m._resolve_conflict(300.0, 100.0, 'keep_both') == 'rename'

def test_conflict_prefer_newer_remote_is_newer(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME','user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    m = build_manager('prefer_newer')
    # remote newer -> download
    assert m._resolve_conflict(400.0, 100.0, 'prefer_newer') == 'download'

def test_conflict_prefer_newer_local_is_newer(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME','user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    m = build_manager('prefer_newer')
    # local newer -> skip
    assert m._resolve_conflict(100.0, 400.0, 'prefer_newer') == 'skip'
