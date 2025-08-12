import argparse
import signal
import sys
from typing import TYPE_CHECKING

from . import __version__
from .config import Config

if TYPE_CHECKING:  # pragma: no cover
    from .sync_manager import SyncManager  # noqa: F401


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="iCloud Sync for Linux")
    parser.add_argument("--once", action="store_true", help="Run one remote check then exit")
    parser.add_argument("--interval", type=int, help="Override sync interval seconds")
    parser.add_argument("--dry-run", action="store_true", help="Perform operations without modifying remote or local filesystem")
    parser.add_argument("--include", help="Comma-separated glob patterns to include (overrides env INCLUDE_PATTERNS)")
    parser.add_argument("--exclude", help="Comma-separated glob patterns to exclude (overrides env EXCLUDE_PATTERNS)")
    parser.add_argument("--no-remote", action="store_true", help="Run without contacting iCloud (local watcher only)")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--verbose-decisions", action="store_true", help="Log per-file decision details at INFO level")
    parser.add_argument("--stats-interval", type=int, help="Emit periodic stats every N seconds")
    parser.add_argument("--progress-summary", action="store_true", help="Log a summary line after each remote pass")
    parser.add_argument("--metrics-http", action="store_true", help="Enable simple HTTP metrics endpoint")
    parser.add_argument("--metrics-port", type=int, help="Port for metrics HTTP server (default from env METRICS_PORT)")
    parser.add_argument("--status", action="store_true", help="Print current state summary (no sync) and exit")
    parser.add_argument("--metrics-snapshot", action="store_true", help="Print current metrics JSON (no sync) and exit")
    parser.add_argument("--relogin", action="store_true", help="Purge cached session & force fresh 2FA login")
    parser.add_argument("--no-auto-reauth", action="store_true", help="Disable automatic re-auth attempts on 421/423 errors")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print(f"icloud-sync {__version__}")
        return 0
    if args.status or args.metrics_snapshot:
        config = Config.load()
        state_path = config.state_file
        import json, os, time
        summary = {}
        if os.path.exists(state_path):
            try:
                with open(state_path, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                files = st.get('files', {})
                summary = {
                    'files_tracked': len(files),
                    'remote_entries': len(st.get('remote_snapshot', [])),
                    'state_file': state_path,
                    'sample_files': list(files.keys())[:10],
                    'generated_at': int(time.time()),
                }
            except Exception as e:  # pragma: no cover
                summary = {'error': f'Failed to read state file: {e}', 'state_file': state_path}
        else:
            summary = {'files_tracked': 0, 'remote_entries': 0, 'state_file': state_path, 'missing': True}
        if args.metrics_snapshot:
            # Basic metrics derived from state; if running service metrics are richer.
            summary = {
                **summary,
                'metrics': {
                    'uploads': 0,
                    'downloads': 0,
                    'passes_ok': 0,
                    'passes_fail': 0,
                }
            }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    config = Config.load()
    if args.interval:
        config.sync_interval = max(5, args.interval)
    if args.dry_run:
        config.dry_run = True
    if args.include:
        config.include_patterns = tuple(p.strip() for p in args.include.split(',') if p.strip())
    if args.exclude:
        config.exclude_patterns = tuple(p.strip() for p in args.exclude.split(',') if p.strip())
    if args.no_remote:
        config.no_remote = True
    if args.verbose_decisions:
        config.verbose_decisions = True
    if args.stats_interval is not None:
        config.stats_interval = max(0, args.stats_interval)
    if args.progress_summary:
        config.progress_summary = True
    if args.metrics_http:
        config.enable_metrics_http = True
    if args.metrics_port is not None:
        config.metrics_port = args.metrics_port
    if args.relogin:
        config.force_relogin = True
    if args.no_auto_reauth:
        config.auto_reauth = False

    # Lazy import to avoid requiring optional heavy deps for --version or config-only actions
    from .sync_manager import SyncManager  # noqa: PLC0415
    manager = SyncManager(config)

    def handle_sigterm(signum, frame):  # pragma: no cover - signal path
        manager.stop_event.set()
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    if args.once:
        manager.check_remote_changes()
        return 0

    manager.start()
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
