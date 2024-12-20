from .config import Config
from .sync_manager import SyncManager

def main():
    config = Config()
    sync_manager = SyncManager(config)
    sync_manager.start()

if __name__ == '__main__':
    main()
