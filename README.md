# iCloud-Sync-Linux

A tool to synchronize iCloud Drive content with Linux systems.

## Description

This project provides a solution for Linux users to access and sync their iCloud Drive content locally. It enables seamless integration between Apple's iCloud service and Linux operating systems.

## Requirements

- Python 3.9+ (tested with 3.12)
- pip (Python package manager)
- (Optional) iCloud account credentials (or run in NO_REMOTE mode)
- Linux operating system

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/iCloud-Sync-Linux.git
cd iCloud-Sync-Linux
```

2. (Recommended) Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Configuration (.env)

Configuration is supplied via environment variables (supports a `.env` file). See `.env.example` for a quick start.

Key environment variables:
```
ICLOUD_USERNAME=your.email@example.com      # required unless NO_REMOTE=1
ICLOUD_PASSWORD=app_specific_password       # optional if using keyring or existing session
LOCAL_DIRECTORY=~/iCloud                    # local root directory
SYNC_INTERVAL=300                           # seconds between remote polling passes
LOG_LEVEL=INFO
LOG_JSON=0                               # 1 for structured JSON logs
LOG_FILE=~/icloud-sync.log
FORCE_RELOGIN=0                          # 1 to purge cached session & force fresh 2FA
AUTO_REAUTH=1                            # auto attempts to recover from 421/423 auth/lock errors
AUTO_REAUTH_MAX_ATTEMPTS=3               # maximum automatic re-auth attempts (-1 disables)
ICLOUD_2FA_CODE=                            # optional one-time (interactive prompt preferred)
STATE_FILE=~/iCloud/.icloud_sync_state.json
ENABLE_CHECKSUM=0                           # 1 to enable SHA-256 hashing
INCLUDE_PATTERNS=*.txt,docs/*.md            # comma separated globs (whitelist)
EXCLUDE_PATTERNS=*.bak,*.tmp                # comma separated globs (blacklist)
IGNORE_PATTERNS=*.partial,~*                # always ignored (takes precedence)
DRY_RUN=0                                   # 1 to simulate actions
NO_REMOTE=0                                 # 1 for local-only (no iCloud calls)
CONFLICT_STRATEGY=prefer_newer              # prefer_newer|prefer_local|prefer_remote|keep_both
USE_KEYRING=0                               # 1 to retrieve/store password in system keyring
KEYRING_SERVICE=icloud-sync                 # keyring service label
VERBOSE_DECISIONS=0                         # 1 to log per-file decisions at INFO
STATS_INTERVAL=0                            # >0 to emit periodic STATS lines
PROGRESS_SUMMARY=0                          # 1 to log summary after each pass
METRICS_HTTP=0                              # 1 to enable simple HTTP JSON metrics
METRICS_PORT=8787                           # port for metrics (if METRICS_HTTP=1)
METRICS_HOST=127.0.0.1                      # bind host for metrics
METRICS_PATH=/metrics                       # metrics endpoint path
METRICS_TOKEN=                              # optional bearer token
OP_DELAY_MS=0                               # optional per-file sleep (ms) to reduce CPU burst
MAX_DOWNLOADS_PER_PASS=0                    # limit downloads per polling pass (0 = unlimited)
```

Conflict strategies:
* prefer_newer (default): compare modification times (1s tolerance); skip if local not older
* prefer_local: never overwrite local; skip remote download
* prefer_remote: always download remote version
* keep_both: local is renamed with a `.conflict-<timestamp>` suffix then remote downloaded

Checksum mode (`ENABLE_CHECKSUM=1`) stores a SHA-256 hash after downloads/uploads to help detect silent corruption (best-effort; not mandatory for sync decisions by default).

Keyring integration: set `USE_KEYRING=1` to read an existing password or store the first successful one. This avoids putting secrets in plain-text `.env` files.

Two-factor: The library will prompt interactively when needed; you may pre-set `ICLOUD_2FA_CODE` for CI or first-run automation (one-time).

## Usage

Run the module entry point:
```bash
python -m icloud_sync
```

Optional flags:
```bash
python -m icloud_sync --once            # perform one remote check then exit
python -m icloud_sync --interval 600    # override sync interval (seconds)
python -m icloud_sync --dry-run         # simulate actions
python -m icloud_sync --include '*.txt,docs/*.md' --exclude '*.bak'  # pattern filters
python -m icloud_sync --no-remote       # force local-only mode even if creds provided
python -m icloud_sync --version         # print version and exit
python -m icloud_sync --verbose-decisions  # per-file decision logs at INFO
python -m icloud_sync --stats-interval 300 # STATS line every 5 minutes
python -m icloud_sync --progress-summary   # per-pass summary lines
python -m icloud_sync --metrics-http --metrics-port 8787  # enable HTTP metrics
python -m icloud_sync --status           # print current tracked state summary (no sync)
python -m icloud_sync --metrics-snapshot # print derived metrics snapshot (no sync)
python -m icloud_sync --relogin          # purge cached session & force 2FA flow
python -m icloud_sync --no-auto-reauth   # disable automatic re-auth retries
```

Verbose decision logging:
Set VERBOSE_DECISIONS=1 in env or use --verbose-decisions to elevate per-file decision messages (uploads, downloads, conflicts) to INFO level (otherwise they appear at DEBUG). This helps observe real-time sync reasoning.
Additional env toggles:
* VERIFY_DOWNLOAD=1 : when combined with ENABLE_CHECKSUM=1 re-hashes after download (basic integrity check)
* STATS_INTERVAL, PROGRESS_SUMMARY for runtime metrics
* METRICS_HTTP / METRICS_PORT / METRICS_TOKEN for JSON metrics endpoint
* LOG_JSON=1 for structured logs (fields: ts, level, message, file, action, path, etc.)
```

For a background (system) service consider creating a systemd unit file pointing to the virtualenv python and running `python -m icloud_sync`.

## Current Status / Roadmap

Implemented:
* Environment/CLI configuration with validation
* Logging (rotating file + console)
* Local filesystem watch (watchdog) + periodic remote polling
* iCloud authentication (2FA supported)
* State persistence (JSON) with optional checksum hashing
* Sync operations: upload, download, remote deletion propagation
* Include / exclude pattern filtering
* Dry-run mode (state updates without remote changes)
* Conflict strategies (prefer_newer / prefer_local / prefer_remote / keep_both)
* Automatic exponential backoff with jitter on remote errors
* Keyring integration (optional)
* Automatic no-remote fallback if password missing (useful for tests/inspection)
* Metrics: per-pass summaries, periodic stats, metrics snapshot CLI output, optional HTTP JSON endpoint
* Additional auth metrics (auth_blocked_events, reauth_attempts)
* Optional structured JSON logging (LOG_JSON=1) for log aggregation tools
* Graceful watchdog fallback (still runs remote polling + manual passes if watchdog not installed)
* Basic handling / guidance for authentication lock (421/423) conditions

Planned / TODO:
* Incremental remote delta (efficiency) / push-style updates
* Partial / resumable transfers
* Optional post-download checksum verification enforcement
* systemd unit template refinement & packaging (wheel / PyPI)
* More granular auth state exposure & manual re-auth trigger without restart

## Advanced Data Protection (ADP) Compatibility

Apple's Advanced Data Protection (end‑to‑end encryption for iCloud data) is currently NOT supported by the underlying `pyicloud` library used here. If Advanced Data Protection is enabled for your Apple ID, iCloud Drive listing requests may consistently fail with HTTP 421 / 423 ("Locked") despite successful credential / 2FA validation. Symptoms you may see in logs:

```
REMOTE list error at prefix='': Locked (423)
Remote listing blocked (auth/lock). Will attempt auto re-auth ...
Exceeded automatic re-auth attempts; use --relogin for manual 2FA.
```

If you have ADP enabled and encounter these errors:
1. Visit https://appleid.apple.com/account/manage and confirm Advanced Data Protection status.
2. Temporarily disable Advanced Data Protection (this may require access to your recovery contact / key).
3. Re-run the tool with `--relogin` (or set `FORCE_RELOGIN=1`) to establish a fresh trusted session.
4. After initial sync completes, you can attempt to re‑enable ADP, but current functionality may break again until upstream library support is added.

Status: This is a documented limitation; a future enhancement may detect ADP more explicitly or leverage an updated API when available. Contributions or upstream library improvements are welcome.

## Packaging / Installation (optional)

Editable install:
```bash
pip install -e .
```
Then run via entry point:
```bash
icloud-sync --interval 600
```

## Running Tests
```bash
pip install pytest
pytest -q
```
## Packaging
Build a wheel / sdist:
```bash
python -m build
```
Install locally:
```bash
pip install dist/icloud_sync_linux-*.whl
```

## Example .env
```
# Minimal
ICLOUD_USERNAME=your.email@example.com
ICLOUD_PASSWORD=app_specific_password

# Optional extras
ENABLE_CHECKSUM=1
CONFLICT_STRATEGY=keep_both
INCLUDE_PATTERNS=*.txt,docs/*.md
EXCLUDE_PATTERNS=*.bak,*.tmp
USE_KEYRING=1
```

## systemd Service Example
See `systemd/icloud-sync.service.example`. Copy to `/etc/systemd/system/icloud-sync@USERNAME.service` (or a fixed name), adjust paths/users, create `/etc/default/icloud-sync` with exported environment variables or point `EnvironmentFile` to an `.env` styled file (KEY=VALUE per line), then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now icloud-sync
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This is an unofficial tool and is not affiliated with Apple Inc.