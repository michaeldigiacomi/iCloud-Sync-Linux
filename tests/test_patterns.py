import os
from icloud_sync.config import Config
from icloud_sync.sync_manager import SyncManager


def build_manager(tmp_path, include=None, exclude=None):
    os.environ['ICLOUD_USERNAME'] = 'user@test'
    os.environ['LOCAL_DIRECTORY'] = str(tmp_path)
    cfg = Config.load()
    cfg.no_remote = True
    if include is not None:
        cfg.include_patterns = tuple(include)
    if exclude is not None:
        cfg.exclude_patterns = tuple(exclude)
    return SyncManager(cfg)


def test_include_only(tmp_path):
    m = build_manager(tmp_path, include=['*.txt'])
    assert m._path_included('file.txt') is True
    assert m._path_included('file.md') is False


def test_exclude_only(tmp_path):
    m = build_manager(tmp_path, exclude=['*.bak'])
    assert m._path_included('doc.txt') is True
    assert m._path_included('old.bak') is False


def test_include_and_exclude(tmp_path):
    m = build_manager(tmp_path, include=['*.txt','*.md'], exclude=['secret.*'])
    assert m._path_included('note.txt') is True
    assert m._path_included('secret.txt') is False
    assert m._path_included('image.png') is False


def test_ignore_patterns_precedence(monkeypatch, tmp_path):
    os.environ['ICLOUD_USERNAME'] = 'user@test'
    os.environ['LOCAL_DIRECTORY'] = str(tmp_path)
    os.environ['INCLUDE_PATTERNS'] = '*.txt'
    os.environ['IGNORE_PATTERNS'] = 'ignore*.txt'
    cfg = Config.load()
    cfg.no_remote = True
    m = SyncManager(cfg)
    assert m._path_included('file.txt') is True  # included
    assert m._path_included('ignore_this.txt') is False  # ignored even though matches include
