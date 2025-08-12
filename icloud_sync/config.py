"""Configuration loader for iCloud-Sync-Linux.

Reads environment variables (with optional .env support) and exposes a typed
Config object used by the rest of the application.
"""

from __future__ import annotations
"""Configuration loader for iCloud-Sync-Linux.

Reads environment variables (with optional .env support) and exposes a typed
Config object used by the rest of the application.
"""

import os
from dataclasses import dataclass
from typing import Optional, Tuple

try:  # optional dependency in tests/runtime
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - fallback if dotenv missing
    def load_dotenv(*args, **kwargs):
        return False


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_int(name: str, value: Optional[str], default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except Exception as e:
        # match tests expecting a ValueError message to include this key
        raise ValueError(f"Invalid {name}: {value}") from e


def _parse_patterns(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return tuple()
    parts = [p.strip() for p in value.split(",")]
    return tuple(p for p in parts if p)


@dataclass
class Config:
    # Credentials / auth
    icloud_username: str = ""
    icloud_password: Optional[str] = None
    icloud_2fa_code: Optional[str] = None
    use_keyring: bool = False
    keyring_service: str = "icloud-sync"

    # Paths / files
    local_directory: str = os.path.expanduser("~/iCloud")
    state_file: str = os.path.expanduser("~/iCloud/.icloud_sync_state.json")
    log_file: str = os.path.expanduser("~/icloud-sync.log")

    # Behavior / operation
    sync_interval: int = 300
    dry_run: bool = False
    no_remote: bool = False
    enable_checksum: bool = False
    verify_download: bool = False
    include_patterns: Tuple[str, ...] = tuple()
    exclude_patterns: Tuple[str, ...] = tuple()
    ignore_patterns: Tuple[str, ...] = tuple()  # always ignored (takes precedence over include)
    conflict_strategy: str = "prefer_newer"  # prefer_newer|prefer_local|prefer_remote|keep_both
    force_relogin: bool = False  # force removal of cached pyicloud session before auth
    auto_reauth: bool = True  # attempt transparent re-auth after auth/lock errors
    auto_reauth_max_attempts: int = 3  # max automatic re-auth attempts before giving up
    # Performance / pacing
    op_delay_ms: int = 0  # sleep between file operations (upload/download/delete) to reduce CPU/network burst
    max_downloads_per_pass: int = 0  # cap downloads per pass (0 = unlimited)

    # Logging
    log_level: str = "INFO"
    verbose_decisions: bool = False
    log_json: bool = False

    # Stats / metrics
    stats_interval: int = 0
    progress_summary: bool = False
    enable_metrics_http: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 8787
    metrics_path: str = "/metrics"
    metrics_token: str = ""

    @staticmethod
    def load() -> "Config":
        # Load .env if present
        load_dotenv()

        # Credentials
        username = os.getenv("ICLOUD_USERNAME", "")
        password = os.getenv("ICLOUD_PASSWORD") or None
        code_2fa = os.getenv("ICLOUD_2FA_CODE") or None
        use_keyring = _parse_bool(os.getenv("USE_KEYRING"), False)
        keyring_service = os.getenv("KEYRING_SERVICE", "icloud-sync")

        # Paths
        local_dir = os.path.expanduser(os.getenv("LOCAL_DIRECTORY", "~/Icloud"))
        if "LOCAL_DIRECTORY" not in os.environ:
            # Normalize default capitalisation when not explicitly set
            local_dir = os.path.expanduser("~/iCloud")
        state_file = os.path.expanduser(os.getenv("STATE_FILE", "~/iCloud/.icloud_sync_state.json"))
        log_file = os.path.expanduser(os.getenv("LOG_FILE", "~/icloud-sync.log"))

        # Behavior / patterns / conflict
        sync_interval = _parse_int("SYNC_INTERVAL", os.getenv("SYNC_INTERVAL"), 300)
        if sync_interval < 5:
            sync_interval = 5
        dry_run = _parse_bool(os.getenv("DRY_RUN"), False)
        no_remote = _parse_bool(os.getenv("NO_REMOTE"), False)
        enable_checksum = _parse_bool(os.getenv("ENABLE_CHECKSUM"), False)
        verify_download = _parse_bool(os.getenv("VERIFY_DOWNLOAD"), False)
        include_patterns = _parse_patterns(os.getenv("INCLUDE_PATTERNS"))
        exclude_patterns = _parse_patterns(os.getenv("EXCLUDE_PATTERNS"))
        ignore_patterns = _parse_patterns(os.getenv("IGNORE_PATTERNS"))
        conflict_strategy = os.getenv("CONFLICT_STRATEGY", "prefer_newer").strip()
        if conflict_strategy not in {"prefer_newer", "prefer_local", "prefer_remote", "keep_both"}:
            conflict_strategy = "prefer_newer"
        force_relogin = _parse_bool(os.getenv("FORCE_RELOGIN"), False)
        auto_reauth = _parse_bool(os.getenv("AUTO_REAUTH"), True)
        auto_reauth_max_attempts = _parse_int("AUTO_REAUTH_MAX_ATTEMPTS", os.getenv("AUTO_REAUTH_MAX_ATTEMPTS"), 3)
        if auto_reauth_max_attempts < 0:
            auto_reauth_max_attempts = 0
        op_delay_ms = _parse_int("OP_DELAY_MS", os.getenv("OP_DELAY_MS"), 0)
        if op_delay_ms < 0:
            op_delay_ms = 0
        max_downloads_per_pass = _parse_int("MAX_DOWNLOADS_PER_PASS", os.getenv("MAX_DOWNLOADS_PER_PASS"), 0)
        if max_downloads_per_pass < 0:
            max_downloads_per_pass = 0

        # Logging
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        verbose_decisions = _parse_bool(os.getenv("VERBOSE_DECISIONS"), False)
        log_json = _parse_bool(os.getenv("LOG_JSON"), False)

        # Metrics / stats
        stats_interval = _parse_int("STATS_INTERVAL", os.getenv("STATS_INTERVAL"), 0)
        if stats_interval < 0:
            stats_interval = 0
        progress_summary = _parse_bool(os.getenv("PROGRESS_SUMMARY"), False)
        enable_metrics_http = _parse_bool(os.getenv("METRICS_HTTP"), False)
        metrics_port = _parse_int("METRICS_PORT", os.getenv("METRICS_PORT"), 8787)
        metrics_host = os.getenv("METRICS_HOST", "127.0.0.1")
        metrics_path = os.getenv("METRICS_PATH", "/metrics")
        metrics_token = os.getenv("METRICS_TOKEN", "")

        # Ensure directories
        try:
            os.makedirs(os.path.expanduser(os.path.dirname(state_file)), exist_ok=True)
            os.makedirs(os.path.expanduser(local_dir), exist_ok=True)
        except Exception:  # pragma: no cover
            pass

        return Config(
            icloud_username=username,
            icloud_password=password,
            icloud_2fa_code=code_2fa,
            use_keyring=use_keyring,
            keyring_service=keyring_service,
            local_directory=local_dir,
            state_file=state_file,
            log_file=log_file,
            sync_interval=sync_interval,
            dry_run=dry_run,
            no_remote=no_remote,
            enable_checksum=enable_checksum,
            verify_download=verify_download,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            ignore_patterns=ignore_patterns,
            conflict_strategy=conflict_strategy,
            force_relogin=force_relogin,
            auto_reauth=auto_reauth,
            auto_reauth_max_attempts=auto_reauth_max_attempts,
            op_delay_ms=op_delay_ms,
            max_downloads_per_pass=max_downloads_per_pass,
            log_level=log_level,
            verbose_decisions=verbose_decisions,
            log_json=log_json,
            stats_interval=stats_interval,
            progress_summary=progress_summary,
            enable_metrics_http=enable_metrics_http,
            metrics_host=metrics_host,
            metrics_port=metrics_port,
            metrics_path=metrics_path,
            metrics_token=metrics_token,
        )
