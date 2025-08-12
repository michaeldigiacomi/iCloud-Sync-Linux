import subprocess, sys, os

def test_cli_version():
    result = subprocess.run([sys.executable, '-m', 'icloud_sync', '--version'], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'icloud-sync' in result.stdout

def test_cli_no_remote_once(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME', 'user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    # Force no-remote; should not attempt pyicloud auth
    cp = subprocess.run([sys.executable, '-m', 'icloud_sync', '--once', '--no-remote'], capture_output=True, text=True)
    assert cp.returncode == 0


def test_cli_status(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME', 'user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    # Status should emit JSON summary even before state file exists
    cp = subprocess.run([sys.executable, '-m', 'icloud_sync', '--status'], capture_output=True, text=True)
    assert cp.returncode == 0
    assert 'state_file' in cp.stdout


def test_cli_metrics_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv('ICLOUD_USERNAME', 'user@test')
    monkeypatch.setenv('LOCAL_DIRECTORY', str(tmp_path))
    state = {
        'files': {'a.txt': {'mtime': 1, 'size': 10, 'hash': None, 'last_direction': 'remote->local'}},
        'remote_snapshot': ['a.txt']
    }
    state_file = tmp_path / 'state.json'
    state_file.write_text(__import__('json').dumps(state))
    monkeypatch.setenv('STATE_FILE', str(state_file))
    cp = subprocess.run([sys.executable, '-m', 'icloud_sync', '--metrics-snapshot'], capture_output=True, text=True)
    assert cp.returncode == 0
    import json
    data = json.loads(cp.stdout)
    assert data['files_tracked'] == 1
    assert 'metrics' in data
