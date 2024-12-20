# iCloud-Sync-Linux

A tool to synchronize iCloud Drive content with Linux systems.

## Description

This project provides a solution for Linux users to access and sync their iCloud Drive content locally. It enables seamless integration between Apple's iCloud service and Linux operating systems.

## Requirements

- Python 3.6 or higher
- pip (Python package manager)
- iCloud account credentials
- Linux operating system

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/iCloud-Sync-Linux.git
cd iCloud-Sync-Linux
```

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Create a configuration file:
```bash
cp config.example.yml config.yml
```

2. Edit `config.yml` with your iCloud credentials and desired sync settings:
```yaml
icloud:
  username: your.email@example.com
  password: your_app_specific_password
sync:
  interval: 300  # sync interval in seconds
  local_path: ~/iCloud  # local sync directory
```

Note: It's recommended to use an app-specific password instead of your main iCloud password.

## Usage

1. Start the sync service:
```bash
python icloud_sync.py
```

2. To run in background:
```bash
python icloud_sync.py --daemon
```

3. To stop the service:
```bash
python icloud_sync.py --stop
```

## Features

- Two-way synchronization between iCloud Drive and local directory
- Automatic conflict resolution
- Support for all iCloud Drive file types
- Background sync service
- Configurable sync intervals

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This is an unofficial tool and is not affiliated with Apple Inc.