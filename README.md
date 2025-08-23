# Odoo Backup Manager

A comprehensive backup and restore utility for Odoo instances, supporting both database and filestore operations with local and remote (SSH) connections.

## Features

- 🗄️ **Complete Backup & Restore**: Handles both PostgreSQL database and Odoo filestore
- 🔒 **Secure Storage**: Encrypted password storage for connection profiles
- 🌐 **Remote Support**: Backup/restore from remote servers via SSH
- 💾 **Connection Profiles**: Save and reuse connection configurations
- 🖥️ **Dual Interface**: Both CLI and GUI interfaces available
- 📦 **Archive Management**: Creates compressed archives with metadata
- 🔄 **Flexible Operations**: Backup only, restore only, or backup & restore in one operation
- 🛡️ **Production Protection**: Prevent accidental restores to production databases with allow_restore flag

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/jpsteil/odoo-backup-manager.git
cd odoo-backup-manager

# Install the package
pip install -e .

# Or install with GUI support
pip install -e ".[gui]"

# For development
pip install -r requirements-dev.txt
```

### Using pip

```bash
pip install odoo-backup-manager
```

## Prerequisites

- Python 3.8 or higher
- PostgreSQL client tools (`pg_dump`, `pg_restore`, `psql`)
- tar command-line utility
- tkinter (for GUI mode) - usually included with Python

### Installing PostgreSQL Client Tools

#### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install postgresql-client
```

#### RHEL/CentOS/Fedora
```bash
sudo dnf install postgresql
```

#### macOS
```bash
brew install postgresql
```

## Usage

### Command Line Interface

#### Basic Backup
```bash
# Backup database and filestore
odoo-backup backup --name mydb --host localhost --user odoo --filestore /var/lib/odoo/filestore

# Backup database only
odoo-backup backup --name mydb --host localhost --user odoo --no-filestore

# Backup with specific output directory
odoo-backup backup --name mydb --host localhost --user odoo --output-dir /backups
```

#### Basic Restore
```bash
# Restore from backup file
odoo-backup restore --file backup_MYDB_20240101_120000.tar.gz --name newdb --host localhost --user odoo

# Restore database only (skip filestore)
odoo-backup restore --file backup.tar.gz --name newdb --host localhost --user odoo --no-filestore
```

#### Connection Management
```bash
# List saved connections
odoo-backup connections list

# Save a new connection (protected by default)
odoo-backup connections save --name prod --host db.example.com --user odoo --database mydb --filestore /var/lib/odoo

# Save a development connection with restore allowed
odoo-backup connections save --name dev --host localhost --user odoo --database devdb --filestore /var/lib/odoo --allow-restore

# Test a connection
odoo-backup connections test prod

# Delete a connection
odoo-backup connections delete prod
```

#### Using Saved Connections
```bash
# Backup using saved connection
odoo-backup backup --connection prod --name mydb

# Restore using saved connection
odoo-backup restore --connection dev --file backup.tar.gz --name restored_db
```

#### From Odoo Configuration File
```bash
# Parse odoo.conf and create backup
odoo-backup from-config /etc/odoo/odoo.conf --backup
```

### Graphical User Interface

Launch the GUI:
```bash
# Using the command
odoo-backup gui

# Or using the dedicated launcher
odoo-backup-gui
```

The GUI provides:
- Visual connection management
- Backup/restore operations with progress tracking
- Connection testing
- Backup file management
- Operation logs

## Configuration

The tool stores its configuration in `~/.config/odoo_backup_tool/`:
- `config.json`: Application settings
- `connections.db`: Encrypted connection profiles

### Default Configuration

```json
{
  "backup_dir": "~/odoo_backups",
  "default_odoo_version": "17.0",
  "pg_dump_options": ["--no-owner", "--no-acl"],
  "compression_level": 6,
  "max_backup_age_days": 30,
  "auto_cleanup": false,
  "verbose": false
}
```

## Backup File Structure

Backup archives contain:
- `database.sql`: PostgreSQL database dump
- `filestore.tar.gz`: Compressed filestore data (if included)
- `metadata.json`: Backup metadata (timestamp, database name, Odoo version)

## Security

- Passwords are encrypted using machine-specific keys
- SSH connections support both password and key-based authentication
- No passwords are stored in plain text
- Production database protection with `allow_restore` flag (defaults to False)
  - Connections are protected from restore operations by default
  - Must explicitly enable restore capability for non-production databases
  - GUI filters destination connections based on allow_restore setting
  - CLI validates allow_restore before executing restore operations

## Development

### Project Structure

```
odoo_backup_tool/
├── odoo_backup_tool/
│   ├── __init__.py
│   ├── cli.py              # CLI entry point
│   ├── gui_launcher.py     # GUI launcher
│   ├── core/
│   │   ├── __init__.py
│   │   └── backup_restore.py  # Core backup/restore logic
│   ├── db/
│   │   ├── __init__.py
│   │   └── connection_manager.py  # Connection management
│   ├── gui/
│   │   ├── __init__.py
│   │   └── main_window.py  # GUI implementation
│   └── utils/
│       ├── __init__.py
│       └── config.py       # Configuration management
├── tests/                  # Test suite
├── setup.py               # Package setup
├── requirements.txt       # Production dependencies
├── requirements-dev.txt   # Development dependencies
└── README.md
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=odoo_backup_tool

# Run specific test file
pytest tests/test_backup_restore.py
```

### Code Formatting

```bash
# Format code with black
black odoo_backup_tool/

# Check code style
flake8 odoo_backup_tool/

# Type checking
mypy odoo_backup_tool/
```

## Troubleshooting

### Common Issues

1. **Missing PostgreSQL tools**
   - Install PostgreSQL client tools for your system
   - Ensure `pg_dump`, `pg_restore`, and `psql` are in PATH

2. **Permission denied errors**
   - Ensure the user has read access to filestore directory
   - Ensure the user has write access to backup directory

3. **GUI not launching**
   - Install tkinter: `sudo apt-get install python3-tk`

4. **SSH connection failures**
   - Verify SSH credentials and connectivity
   - Check if SSH key has proper permissions (600)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and ensure code quality
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

- GitHub Issues: https://github.com/yourusername/odoo-backup-tool/issues
- Documentation: https://github.com/yourusername/odoo-backup-tool/wiki

## Credits

Developed for the Odoo community to simplify backup and restore operations.