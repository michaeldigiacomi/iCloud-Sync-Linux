import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.icloud_username = os.getenv('ICLOUD_USERNAME')
        self.icloud_password = os.getenv('ICLOUD_PASSWORD')
        self.local_directory = os.getenv('LOCAL_DIRECTORY', os.path.expanduser('~/iCloud'))
        self.sync_interval = int(os.getenv('SYNC_INTERVAL', '300'))
        self.log_file = os.getenv('LOG_FILE', os.path.expanduser('~/icloud-sync.log'))
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
