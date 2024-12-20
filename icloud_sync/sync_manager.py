import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pyicloud import PyiCloudService
import logging
from logging.handlers import RotatingFileHandler

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, sync_manager):
        self.sync_manager = sync_manager

    def on_modified(self, event):
        if not event.is_directory:
            self.sync_manager.handle_local_change(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self.sync_manager.handle_local_change(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.sync_manager.handle_local_deletion(event.src_path)

class SyncManager:
    def __init__(self, config):
        self.config = config
        self.api = PyiCloudService(config.icloud_username, config.icloud_password)
        self.observer = Observer()
        self.setup_local_directory()
        self.setup_logging()

    def setup_logging(self):
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(self.config.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Set up logging format
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.log_level.upper()))

        # File handler (rotating log file, max 10MB, keep 5 backup files)
        file_handler = RotatingFileHandler(
            self.config.log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        logging.info("Logging system initialized")

    def setup_local_directory(self):
        if not os.path.exists(self.config.local_directory):
            os.makedirs(self.config.local_directory)

    def start(self):
        event_handler = FileChangeHandler(self)
        self.observer.schedule(event_handler, self.config.local_directory, recursive=True)
        self.observer.start()
        try:
            while True:
                self.check_remote_changes()
                time.sleep(self.config.sync_interval)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()

    def handle_local_change(self, file_path):
        logging.info(f"Local change detected: {file_path}")
        # Implement file upload logic

    def handle_local_deletion(self, file_path):
        logging.info(f"Local deletion detected: {file_path}")
        # Implement remote deletion logic

    def check_remote_changes(self):
        logging.info("Checking for remote changes...")
        # Implement remote change detection and download logic
