"""Clean single SyncManager implementation (duplicate-free)."""

from __future__ import annotations

import os, time, threading, json, hashlib, random, fnmatch, logging, socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Dict, Any, Iterable, Tuple, Callable
from logging.handlers import RotatingFileHandler
try:
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler  # type: ignore
    HAS_WATCHDOG = True
except Exception:  # pragma: no cover
    HAS_WATCHDOG = False
    class FileSystemEventHandler:  # minimal stub
        pass
    class Observer:  # minimal no-op stub
        def schedule(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
        def join(self, timeout=None): pass
        def is_alive(self): return False
try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover
    keyring = None
from .config import Config


class AuthBlockedError(Exception):
    """Raised internally when remote enumeration is blocked due to auth / lock (421/423)."""
    pass


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, sync_manager: "SyncManager"): self.sync_manager = sync_manager
    def on_modified(self, e):  # type: ignore[override]
        if not e.is_directory: self.sync_manager.handle_local_change(e.src_path)
    def on_created(self, e):  # type: ignore[override]
        if not e.is_directory: self.sync_manager.handle_local_change(e.src_path)
    def on_deleted(self, e):  # type: ignore[override]
        if not e.is_directory: self.sync_manager.handle_local_deletion(e.src_path)


class SyncManager:
    def __init__(self, config: Config):
        self.config = config
        # Auto-fallback to no_remote when no password (facilitates tests / offline usage)
        if not self.config.no_remote and not self.config.icloud_password:
            self.config.no_remote = True
            logging.getLogger().info("No password provided; running in no-remote mode automatically")
        self.api = None  # type: ignore[assignment]
        self.observer = Observer() if HAS_WATCHDOG else None
        self.stop_event = threading.Event()
        self._state: Dict[str, Any] = {}
        # Derive relative path of state file if it resides inside the local directory so we can ignore it
        try:
            ld_abs = os.path.abspath(os.path.expanduser(self.config.local_directory))
            sf_abs = os.path.abspath(os.path.expanduser(self.config.state_file))
            if sf_abs.startswith(ld_abs + os.sep):
                self._state_rel = os.path.relpath(sf_abs, ld_abs)
            else:
                self._state_rel = None
        except Exception:  # pragma: no cover - defensive
            self._state_rel = None
        # Metrics
        self._metrics = {
            "uploads": 0,
            "downloads": 0,
            "remote_deletions": 0,
            "local_deletions": 0,
            "conflicts": 0,
            "conflict_skipped": 0,
            "conflict_renamed": 0,
            "passes_ok": 0,
            "passes_fail": 0,
            "bytes_uploaded": 0,
            "bytes_downloaded": 0,
            # auth instrumentation
            "auth_blocked_events": 0,
            "reauth_attempts": 0,
        }
        self._metrics_lock = threading.Lock()
        self._stats_thread: Optional[threading.Thread] = None
        self._http_server: Optional[HTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._setup_local()
        self._setup_logging()
        if not self.config.no_remote:
            if getattr(self.config, 'force_relogin', False):
                self._purge_cached_session()
            self._init_api()
        else:
            logging.info("No-remote mode enabled")
        self._load_state()
        self._auth_blocked = False
        self._reauth_attempts = 0
        self._auth_guidance_logged = False

    # --- setup & state ---
    def _setup_local(self):
        Path(self.config.local_directory).expanduser().mkdir(parents=True, exist_ok=True)
        Path(self.config.state_file).parent.mkdir(parents=True, exist_ok=True)
    def _setup_logging(self):
        d = os.path.dirname(self.config.log_file)
        if d and not os.path.exists(d): os.makedirs(d)
        if self.config.log_json:
            class _JsonFormatter(logging.Formatter):
                def format(self_inner, record: logging.LogRecord) -> str:  # pragma: no cover (simple)
                    import json, time
                    data = {
                        "ts": int(time.time()*1000),
                        "level": record.levelname,
                        "msg": record.getMessage(),
                        "name": record.name,
                    }
                    return json.dumps(data, sort_keys=True)
            fmt = _JsonFormatter()
        else:
            fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        root = logging.getLogger(); root.setLevel(getattr(logging, self.config.log_level.upper()))
        fh = RotatingFileHandler(self.config.log_file, maxBytes=2*1024*1024, backupCount=2); fh.setFormatter(fmt)
        sh = logging.StreamHandler(); sh.setFormatter(fmt)
        root.handlers = []
        root.addHandler(fh); root.addHandler(sh)
    def _init_api(self):
        # Lazy import to avoid hard dependency when running in no-remote mode or tests
        try:
            from pyicloud import PyiCloudService  # type: ignore
        except Exception as e:
            raise RuntimeError("pyicloud is required for remote operations; install dependencies") from e
        password = self.config.icloud_password
        if (not password) and self.config.use_keyring and keyring:
            try:
                password = keyring.get_password(self.config.keyring_service, self.config.icloud_username)
                if password: logging.info("Loaded password from keyring")
            except Exception as e: logging.warning(f"Keyring get failed: {e}")
        try: self.api = PyiCloudService(self.config.icloud_username, password)
        except Exception as e: logging.error(f"iCloud init failed: {e}"); raise
        if hasattr(self.api,'requires_2fa') and self.api.requires_2fa:  # type: ignore[attr-defined]
            code = self.config.icloud_2fa_code or (input("Enter iCloud 2FA code: ") if os.isatty(0) else None)
            if not code: raise RuntimeError("2FA code required")
            if not self.api.validate_2fa_code(code): raise RuntimeError("Invalid 2FA code")
            # Attempt to trust the session to avoid repeated prompts
            try:
                if hasattr(self.api, 'trust_session'):
                    if self.api.trust_session():  # type: ignore[attr-defined]
                        logging.info("iCloud session trusted")
                    else:  # pragma: no cover - network path
                        logging.warning("Failed to mark session as trusted; you may be prompted again later")
            except Exception as e:  # pragma: no cover
                logging.warning(f"trust_session failed: {e}")
        logging.info("iCloud API initialized")
        # Store password if requested and available
        if self.config.use_keyring and keyring and password and not self.config.icloud_password:
            try:
                keyring.set_password(self.config.keyring_service, self.config.icloud_username, password)
                logging.info("Stored password in keyring")
            except Exception as e: logging.warning(f"Keyring set failed: {e}")
    def _load_state(self):
        try:
            with open(self.config.state_file,'r',encoding='utf-8') as f: self._state = json.load(f)
        except FileNotFoundError:
            self._state = {"files":{},"remote_snapshot":[],"remote_meta":{}}
        except Exception as e:
            logging.warning(f"State load failed ({e}); starting new")
            self._state = {"files":{},"remote_snapshot":[],"remote_meta":{}}
        for k, v in {"files":{},"remote_snapshot":[],"remote_meta":{}}.items(): self._state.setdefault(k,v)
    def _save_state(self):
        try:
            with open(self.config.state_file,'w',encoding='utf-8') as f: json.dump(self._state,f,indent=2,sort_keys=True)
        except Exception as e: logging.error(f"State save failed: {e}")

    # --- utilities ---
    def _hash_file(self, path: str) -> Optional[str]:
        if not self.config.enable_checksum: return None
        try:
            h = hashlib.sha256()
            with open(path,'rb') as f:
                for chunk in iter(lambda: f.read(1<<20), b''): h.update(chunk)
            return h.hexdigest()
        except FileNotFoundError: return None
        except Exception as e: logging.debug(f"Hash fail {path}: {e}"); return None
    def _path_included(self, rel: str) -> bool:
        # Ignore patterns take absolute precedence
        if getattr(self.config, 'ignore_patterns', ()):  # backward compatibility if old config objects
            for p in self.config.ignore_patterns:
                if fnmatch.fnmatch(rel, p):
                    return False
        inc, exc = self.config.include_patterns, self.config.exclude_patterns
        if inc and not any(fnmatch.fnmatch(rel,p) for p in inc): return False
        if exc and any(fnmatch.fnmatch(rel,p) for p in exc): return False
        return True
    def _safe_mtime(self, path: str) -> Optional[float]:
        try: return os.stat(path).st_mtime
        except Exception: return None

    # --- lifecycle ---
    def start(self):
        if not self.config.no_remote and not self.api: raise RuntimeError("API not initialized")
        if self.observer is not None:
            handler = FileChangeHandler(self)
            self.observer.schedule(handler,self.config.local_directory,recursive=True)
            self.observer.start()
        else:
            logging.warning("watchdog not installed; local filesystem change detection disabled")
        if self.config.stats_interval > 0 and not self._stats_thread:
            self._stats_thread = threading.Thread(target=self._stats_loop, name="stats", daemon=True)
            self._stats_thread.start()
        if self.config.enable_metrics_http and self.config.metrics_port > 0:
            self._start_http_metrics()
        backoff = self.config.sync_interval
        try:
            while not self.stop_event.is_set():
                t0=time.time(); ok=self.check_remote_changes(); elapsed=time.time()-t0
                with self._metrics_lock:
                    if ok: self._metrics["passes_ok"] += 1
                    else: self._metrics["passes_fail"] += 1
                if self.config.progress_summary:
                    self._emit_pass_summary(elapsed, ok)
                backoff = self.config.sync_interval if ok else min(backoff*2, self.config.sync_interval*12)
                self.stop_event.wait(max(1, backoff - elapsed))
        finally: self.shutdown()
    def shutdown(self):
        if self.observer is not None and self.observer.is_alive():
            self.observer.stop(); self.observer.join(timeout=5)
        self._save_state(); logging.info("Shutdown complete")
        if self._http_server:
            try: self._http_server.shutdown()
            except Exception: pass

    # --- local events ---
    def handle_local_change(self, path: str):
        rel = os.path.relpath(path, self.config.local_directory)
        if rel == getattr(self, '_state_rel', None):  # ignore internal state file writes
            logging.debug("Ignoring internal state file change")
            return
        if not self._path_included(rel): return
        try: st = os.stat(path)
        except FileNotFoundError: return
        meta = {"mtime": st.st_mtime, "size": st.st_size, "hash": self._hash_file(path), "last_direction": "local->remote"}
        if self.config.verbose_decisions:
            logging.info(f"LOCAL CHANGE detected rel={rel} size={st.st_size} mtime={st.st_mtime} dry_run={self.config.dry_run}")
        if not self.config.dry_run:
            self._upload_file(path, rel)
            with self._metrics_lock: self._metrics["uploads"] += 1
        else:
            logging.debug(f"Dry-run: skipped upload {rel}")
        self._state["files"][rel]=meta; self._save_state()
    def handle_local_deletion(self, path: str):
        rel = os.path.relpath(path, self.config.local_directory)
        if rel == getattr(self, '_state_rel', None):  # ignore internal state file deletions
            logging.debug("Ignoring internal state file deletion")
            return
        if not self._path_included(rel): return
        if self.config.verbose_decisions:
            logging.info(f"LOCAL DELETE detected rel={rel} dry_run={self.config.dry_run}")
        if not self.config.dry_run:
            self._delete_remote(rel)
            with self._metrics_lock: self._metrics["remote_deletions"] += 1
        else:
            logging.debug(f"Dry-run: skipped remote delete {rel}")
        self._state["files"].pop(rel, None); self._save_state()

    # --- remote sync ---
    def check_remote_changes(self) -> bool:
        if self.config.no_remote:
            time.sleep(0.01)
            return True
        if not self.api:
            return False
        # Previous pass reported auth block: try pre-pass re-auth if enabled
        if getattr(self, '_auth_blocked', False) and getattr(self.config, 'auto_reauth', True):
            max_attempts = getattr(self.config, 'auto_reauth_max_attempts', 3)
            if self._reauth_attempts < max_attempts:
                self._reauth_attempts += 1
                with self._metrics_lock:
                    self._metrics['reauth_attempts'] = self._reauth_attempts
                self._attempt_reauth(self._reauth_attempts)
                self._auth_blocked = False
            else:
                logging.error("Exceeded automatic re-auth attempts; use --relogin for manual 2FA.")
                self._log_auth_guidance_once()
                return False
        try:
            if self.config.verbose_decisions:
                logging.info("REMOTE PASS start")
            remote: Dict[str, Dict[str, Any]] = {}
            enumeration_attempts = 0
            while True:
                try:
                    for rel, item in self._list_remote():
                        if not self._path_included(rel):
                            continue
                        ts = None
                        try:
                            if hasattr(item, 'date_modified') and item.date_modified:
                                ts = item.date_modified.timestamp()
                        except Exception:
                            ts = None
                        remote[rel] = {"mtime": ts, "size": getattr(item, 'size', None)}
                    break  # success
                except AuthBlockedError:
                    enumeration_attempts += 1
                    if not getattr(self.config, 'auto_reauth', True):
                        self._log_auth_guidance_once()
                        return False
                    max_attempts = getattr(self.config, 'auto_reauth_max_attempts', 3)
                    if self._reauth_attempts >= max_attempts:
                        logging.error("Exceeded automatic re-auth attempts; use --relogin for manual 2FA.")
                        self._log_auth_guidance_once()
                        return False
                    self._reauth_attempts += 1
                    with self._metrics_lock:
                        self._metrics['reauth_attempts'] = self._reauth_attempts
                    self._attempt_reauth(self._reauth_attempts)
                    remote.clear()
                    if enumeration_attempts > 1:  # already retried inside pass
                        self._log_auth_guidance_once()
                        return False
                    continue
            if (self.config.verbose_decisions or self.config.progress_summary or logging.getLogger().isEnabledFor(logging.DEBUG)):
                sample = list(remote.keys())[:10]
                logging.info(f"REMOTE ENUM count={len(remote)} sample={sample}")
            removed = set(self._state["remote_snapshot"]) - set(remote.keys())
            for rel in removed:
                lp = os.path.join(self.config.local_directory, rel)
                meta = self._state["files"].get(rel)
                if meta and meta.get("last_direction")=='remote->local' and os.path.exists(lp) and not self.config.dry_run:
                    try: os.remove(lp)
                    except Exception: pass
                    self._state["files"].pop(rel, None)
                    if self.config.verbose_decisions:
                        logging.info(f"REMOTE DELETION applied rel={rel}")
                    with self._metrics_lock: self._metrics["local_deletions"] += 1
            for rel, rmeta in remote.items():
                lp = os.path.join(self.config.local_directory, rel)
                need=False; rmt=rmeta.get("mtime")
                if not os.path.exists(lp): need=True
                else:
                    try: st=os.stat(lp); need=bool(rmt and rmt>st.st_mtime+1)
                    except FileNotFoundError: need=True
                lmeta=self._state["files"].get(rel)
                if lmeta and lmeta.get("last_direction")=='local->remote' and not need: continue
                if need and lmeta and os.path.exists(lp):
                    action=self._resolve_conflict(rmt,self._safe_mtime(lp),self.config.conflict_strategy)
                    if self.config.verbose_decisions:
                        logging.info(f"CONFLICT rel={rel} strategy={self.config.conflict_strategy} action={action} remote_mtime={rmt} local_mtime={self._safe_mtime(lp)}")
                    with self._metrics_lock: self._metrics["conflicts"] += 1
                    if action=='skip': continue
                    if action=='rename': self._rename_conflict_file(lp)
                if need and not self.config.dry_run:
                    # Respect max downloads per pass if configured
                    if getattr(self.config, 'max_downloads_per_pass', 0) and self._metrics["downloads"] >= self.config.max_downloads_per_pass:
                        if self.config.verbose_decisions:
                            logging.info("DOWNLOAD CAP reached for this pass; remaining files deferred")
                        need = False
                    else:
                        self._download_file(rel)
                        with self._metrics_lock:
                            self._metrics["downloads"] += 1
                        # Optional per-operation delay to smooth CPU usage
                        if getattr(self.config, 'op_delay_ms', 0) > 0:
                            time.sleep(self.config.op_delay_ms / 1000.0)
                if need and self.config.verbose_decisions:
                    logging.info(f"REMOTE DOWNLOAD {'(dry-run skip)' if self.config.dry_run else 'performed'} rel={rel} size={rmeta.get('size')} mtime={rmt}")
                if need: self._state["files"][rel]={"mtime":rmt,"size":rmeta.get("size"),"hash":None,"last_direction":"remote->local"}
            self._state["remote_snapshot"]=sorted(remote.keys()); self._state["remote_meta"]=remote; self._save_state(); return True
        except Exception as e:
            logging.warning(f"Remote pass failed: {e}"); return False

    # --- auth guidance ---
    def _log_auth_guidance_once(self):
        if getattr(self, '_auth_guidance_logged', False):
            return
        self._auth_guidance_logged = True
        logging.error(
            "iCloud Drive remains locked (421/423) after automatic re-auth. Manual steps: "
            "1) Log into https://www.icloud.com, open iCloud Drive, accept any new Terms. "
            "2) Confirm no security alerts or password/account lock at https://appleid.apple.com. "
            "3) On an Apple device, ensure iCloud Drive is enabled and this login is trusted. "
            "4) If you changed password recently, create a new app-specific password and update ICLOUD_PASSWORD. "
            "5) Check if Advanced Data Protection is enabled; if so, it may block pyicloud Drive access (temporarily disable to test). "
            "6) Re-run with --relogin (or FORCE_RELOGIN=1) to force a fresh session. "
            "7) If still locked, wait a few minutes (Apple may rate-limit) before another attempt." )

    # --- remote operations ---
    def _upload_file(self, abs_path: str, rel: str):
        if not self.api: return
        try:
            folder_path,_=os.path.split(rel); folder=self._ensure_remote_folder(folder_path)
            if not folder: return
            def _do():
                with open(abs_path,'rb') as f: folder.upload(f)
            self._with_retries(_do,f"upload {rel}")
            try:
                size = os.path.getsize(abs_path)
                with self._metrics_lock: self._metrics["bytes_uploaded"] += size
            except Exception: pass
            if getattr(self.config, 'op_delay_ms', 0) > 0:
                time.sleep(self.config.op_delay_ms / 1000.0)
        except Exception as e: logging.warning(f"Upload failed {rel}: {e}")
    def _delete_remote(self, rel: str):
        if not self.api: return
        try:
            folder_path,name=os.path.split(rel); folder=self._get_remote_folder(folder_path)
            if not folder or name not in folder.dir(): return
            def _do(): folder[name].delete()
            self._with_retries(_do,f"delete {rel}")
            if getattr(self.config, 'op_delay_ms', 0) > 0:
                time.sleep(self.config.op_delay_ms / 1000.0)
        except Exception as e: logging.warning(f"Delete failed {rel}: {e}")
    def _download_file(self, rel: str):
        if not self.api: return
        try:
            folder_path,name=os.path.split(rel); folder=self._get_remote_folder(folder_path)
            if not folder or name not in folder.dir(): return
            drive_file=folder[name]; lp=os.path.join(self.config.local_directory, rel); os.makedirs(os.path.dirname(lp), exist_ok=True)
            def _do():
                with drive_file.open(stream=True) as resp, open(lp,'wb') as out: out.write(resp.raw.read())
            self._with_retries(_do,f"download {rel}")
            try:
                size = os.path.getsize(lp)
                with self._metrics_lock: self._metrics["bytes_downloaded"] += size
            except Exception: pass
            if hasattr(drive_file,'date_modified') and drive_file.date_modified:
                ts=drive_file.date_modified.timestamp()
                try: os.utime(lp,(ts,ts))
                except Exception: pass
            if self.config.enable_checksum:
                meta=self._state["files"].get(rel)
                new_hash=self._hash_file(lp)
                if meta: meta['hash']=new_hash
                if self.config.verify_download and new_hash is None:
                    logging.warning(f"Checksum verification skipped (hash None) for {rel}")
        except Exception as e: logging.warning(f"Download failed {rel}: {e}")

    # --- remote traversal ---
    def _list_remote(self) -> Iterable[Tuple[str, Any]]:
        if not self.api: return []
        root=self.api.drive; stack:[Tuple[Any,str]]=[(root,"")]
        yielded_any = False
        while stack:
            folder,prefix=stack.pop()
            try:
                names=folder.dir()
                if self.config.verbose_decisions:
                    logging.info(f"REMOTE LIST prefix='{prefix or '/'}' entries={len(names)}")
                    if prefix == "" and not names:
                        logging.info("REMOTE drive.dir() returned empty; possible 2FA/session issue or no iCloud Drive contents")
            except Exception as e:
                if self.config.verbose_decisions:
                    logging.warning(f"REMOTE list error at prefix='{prefix}': {e}")
                if any(code in str(e) for code in ['421','423','Authentication required','Locked']):
                    if not self._auth_blocked:
                        logging.error("Remote listing blocked (auth/lock). Will attempt auto re-auth (disable with AUTO_REAUTH=0).")
                        self._auth_blocked = True
                        with self._metrics_lock:
                            self._metrics['auth_blocked_events'] += 1
                    # escalate to caller for re-auth coordination
                    raise AuthBlockedError()
                continue
            for name in names:
                try: item=folder[name]
                except Exception as e:
                    if self.config.verbose_decisions:
                        logging.debug(f"REMOTE access item failed name={name} prefix='{prefix}': {e}")
                    continue
                rel=os.path.join(prefix,name) if prefix else name
                t=getattr(item,'type',None)
                # Heuristics: treat any object with dir() as folder; others as file if they expose size
                try_has_dir = hasattr(item,'dir')
                if try_has_dir and (t is None or str(t).lower()=="folder"):
                    stack.append((item,rel))
                    continue
                if (t and str(t).lower()=="file") or (not try_has_dir and hasattr(item,'size')):
                    yielded_any = True
                    yield rel, item
                # Some top-level container names (e.g., 'root', 'com.apple.CloudDocs') need descending
                if try_has_dir and str(t).lower() not in {"file","folder"}:  # unknown type, still descend
                    stack.append((item,rel))
        # Fallback: explicitly descend into com.apple.CloudDocs if nothing yielded
        if not yielded_any:
            try:
                top_names = root.dir()
                if 'com.apple.CloudDocs' in top_names:
                    doc_root = root['com.apple.CloudDocs']
                    if self.config.verbose_decisions:
                        logging.info("REMOTE fallback descending into com.apple.CloudDocs")
                    for name in doc_root.dir():
                        try:
                            item = doc_root[name]
                            t = getattr(item,'type',None)
                            if hasattr(item,'dir') and (t is None or str(t).lower()=="folder"):
                                # one more level
                                for sub in item.dir():
                                    try:
                                        sub_item = item[sub]
                                        sub_t = getattr(sub_item,'type',None)
                                        if (sub_t and sub_t.lower()=="file") or (not hasattr(sub_item,'dir') and hasattr(sub_item,'size')):
                                            yield os.path.join(name, sub), sub_item
                                    except Exception:
                                        continue
                            elif (t and str(t).lower()=="file") or (not hasattr(item,'dir') and hasattr(item,'size')):
                                yield name, item
                        except Exception:
                            continue
            except Exception as e:
                if self.config.verbose_decisions:
                    logging.warning(f"REMOTE fallback error: {e}")
    def _ensure_remote_folder(self, folder_path: str):
        if not self.api: return None
        if not folder_path: return self.api.drive
        cur=self.api.drive
        for part in [p for p in folder_path.split(os.sep) if p]:
            try:
                if part not in cur.dir(): cur.mkdir(part)
                cur=cur[part]
            except Exception: return None
        return cur
    def _get_remote_folder(self, folder_path: str):
        if not self.api: return None
        if not folder_path: return self.api.drive
        cur=self.api.drive
        for part in [p for p in folder_path.split(os.sep) if p]:
            try:
                if part not in cur.dir(): return None
                cur=cur[part]
            except Exception: return None
        return cur

    # --- conflict & retry helpers ---
    def _resolve_conflict(self, remote_mtime: Optional[float], local_mtime: Optional[float], strategy: str) -> str:
        if strategy=='prefer_remote': return 'download'
        if strategy=='prefer_local': return 'skip'
        if strategy=='keep_both': return 'rename'
        if remote_mtime and local_mtime and remote_mtime <= local_mtime + 1: return 'skip'
        return 'download'
    def _rename_conflict_file(self, local_path: str):
        if not os.path.exists(local_path): return
        ts=int(time.time()); new=f"{local_path}.conflict-{ts}"
        try: os.rename(local_path,new)
        except Exception: pass
    def _with_retries(self, func: Callable[[], Any], op_name: str, attempts: int=3, base_delay: float=0.5):
        for i in range(1, attempts+1):
            try: func(); return
            except Exception as e:  # pragma: no cover
                if i==attempts: logging.warning(f"{op_name} failed after {attempts} attempts: {e}")
                else:
                    d=base_delay*(2**(i-1))*(0.5+random.random()); logging.debug(f"Retry {i}/{attempts} {op_name}: {e}; sleep {d:.2f}s"); time.sleep(d)
    # --- HTTP metrics ---
    def _start_http_metrics(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self_inner):  # type: ignore
                sm: "SyncManager" = self_inner.server.sync_manager  # type: ignore[attr-defined]
                if self.config.metrics_token:
                    token = self_inner.headers.get('Authorization')
                    if token != f"Bearer {self.config.metrics_token}":
                        self_inner.send_response(401); self_inner.end_headers(); return
                if self_inner.path != self.config.metrics_path:
                    self_inner.send_response(404); self_inner.end_headers(); return
                with sm._metrics_lock: m = dict(sm._metrics)
                body = json.dumps(m).encode('utf-8')
                self_inner.send_response(200)
                self_inner.send_header('Content-Type','application/json')
                self_inner.send_header('Content-Length', str(len(body)))
                self_inner.end_headers(); self_inner.wfile.write(body)
            def log_message(self_inner, format, *args):  # silence
                logging.debug("metrics_http: " + format % args)
        try:
            self._http_server = HTTPServer((self.config.metrics_host, self.config.metrics_port), Handler)
            setattr(self._http_server, 'sync_manager', self)
            self._http_thread = threading.Thread(target=self._http_server.serve_forever, name="metrics-http", daemon=True)
            self._http_thread.start()
            logging.info(f"Metrics HTTP server started on {self.config.metrics_host}:{self.config.metrics_port}{self.config.metrics_path}")
        except Exception as e:
            logging.warning(f"Failed to start metrics server: {e}")
    # --- stats & summaries ---
    def _stats_loop(self):
        while not self.stop_event.wait(self.config.stats_interval):
            self._emit_stats()
    def _emit_stats(self):
        with self._metrics_lock: m=dict(self._metrics)
        logging.info(
            "STATS uploads=%d downloads=%d remote_del=%d local_del=%d conflicts=%d passes_ok=%d passes_fail=%d up_bytes=%d down_bytes=%d" % (
                m["uploads"], m["downloads"], m["remote_deletions"], m["local_deletions"], m["conflicts"], m["passes_ok"], m["passes_fail"], m["bytes_uploaded"], m["bytes_downloaded"],
            )
        )
    def _emit_pass_summary(self, elapsed: float, ok: bool):
        with self._metrics_lock: m=dict(self._metrics)
        logging.info(
            f"PASS {'OK' if ok else 'FAIL'} elapsed={elapsed:.2f}s uploads={m['uploads']} downloads={m['downloads']} conflicts={m['conflicts']} up_bytes={m['bytes_uploaded']} down_bytes={m['bytes_downloaded']}"
        )

    # --- session maintenance ---
    def _purge_cached_session(self):
        """Delete cached pyicloud session directory for this user to force fresh auth."""
        try:
            base = os.path.expanduser("~/.pyicloud")
            if not os.path.isdir(base):
                return
            uname = self.config.icloud_username or ""
            if not uname:
                return
            # pyicloud uses directory named after username (possibly sanitized). Remove any match containing username fragment.
            removed = 0
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                if os.path.isdir(path) and uname.split('@')[0] in entry:
                    try:
                        import shutil
                        shutil.rmtree(path)
                        removed += 1
                    except Exception as e:  # pragma: no cover
                        logging.debug(f"Session purge failed for {path}: {e}")
            logging.info(f"Purged {removed} cached session director{'y' if removed==1 else 'ies'} (force relogin)")
        except Exception as e:  # pragma: no cover
            logging.debug(f"Session purge error: {e}")
    def _attempt_reauth(self, attempt: int):
        logging.info(f"Auto re-auth attempt {attempt}")
        try:
            if attempt == 1:
                self._init_api()
            elif attempt == 2:
                self._purge_cached_session(); self._init_api()
            else:
                logging.warning("Further automatic re-auth attempts suppressed; manual relogin required.")
        except Exception as e:
            logging.warning(f"Auto re-auth attempt {attempt} failed: {e}")

