# Changelog

All notable changes to this project will be documented in this file.

## [1.5.19] - 2025-01-02

### Fixed
- Corrected PyPI package build to properly include console script entry points
- Ensures pipx installation works correctly with both CLI commands

## [1.5.18] - 2025-01-02

### Added
- Console script entry points in pyproject.toml for pipx compatibility
- Proper package configuration for PyPI publication

### Changed
- Moved entry points from setup.py dynamic configuration to explicit pyproject.toml definition
- Package can now be installed via pipx with working CLI commands

## [1.5.17] - 2025-01-02

### Fixed
- Fixed SSH restore to properly detect and copy all filestore directories (was only copying first directory)
- Fixed local restore to properly copy filestore contents without shutil.move errors
- Improved directory detection logic for archives with multiple hash directories (59/, 5a/, 5b/, etc.)
- Added better logging for SSH restore operations to aid debugging

### Changed
- Restored automatic filestore path appending (adds /filestore/DATABASE_NAME if not present)
- SSH restore now uses rsync or tar for more reliable copying of all files and directories
- Local restore now copies contents item by item to avoid move conflicts

### Improved
- More robust handling of different archive structures in both local and SSH restore
- Better error messages and logging during restore operations

## [1.5.16] - 2025-01-02

### Added
- SSH support for remote filestore restoration - can now restore filestores to remote servers via SSH/SFTP
- Better error messages for SSH permission issues during restore

### Fixed
- Fixed "Filestore Only" mode incorrectly attempting database operations
- Fixed backup & restore operation not passing SSH configuration to destination
- Fixed restore confirmation dialog to correctly show what will be deleted based on selected options (db_only/filestore_only)
- Fixed AttributeError 'OdooBackupRestore' object has no attribute 'ssh_manager'
- Fixed SSH connection handling in restore operations to match backup implementation

## [1.5.15] - 2025-01-26

### Fixed
- Fixed NoneType error in backup & restore operations when backup_dir was None
- Fixed missing filestore_only flag in backup & restore configuration
- Fixed remote SSH filestore backup to use correct database-specific path
- Backup & restore now properly saves backup files to backup directory
- Added proper error handling for remote SSH cleanup operations
- Fixed db_only and filestore_only flags not being respected in backup function

### Improved
- Backup & restore operations now always save backup archives for audit trail
- Better path validation in filestore backup operations
- More robust error handling during remote file cleanup
- Filestore path now correctly appends database name for remote backups

## [1.5.14] - 2025-01-26

### Added
- Keyboard shortcuts for all dialogs (Escape to cancel, Enter for default action)
- Auto-focus on first field when dialogs open
- Auto-select existing text in focused fields for easy overwriting
- Proper modal dialog behavior with transient and grab_set

### Improved
- GUI window layout - log area now properly expands to use available space
- Dialog keyboard navigation and usability
- Safer defaults (No button focused on dangerous confirmations)

## [1.5.12] - 2025-01-25

### Documentation
- Updated CLI help text to accurately describe neutralization features
- Updated GUI help dialog to remove incorrect password reset claims
- Updated README to correctly list what gets neutralized
- Removed all references to password resets from documentation
- Added proper description of actual neutralization features

## [1.5.11] - 2025-01-25

### Fixed
- Removed misleading log messages about password resets that weren't actually happening
- Passwords are now preserved during restore (no password resets occur)
- Corrected neutralization log output to match actual operations

## [1.5.10] - 2025-01-25

### Fixed
- Removed dangerous attachment deletion from post-restore cleanup
- Post-restore cleanup now only unfreezes base URL configuration
- Preserved all user documents, images, and attachments during restore

### Security
- Prevented potential data loss from overly aggressive cleanup operations

## [1.5.9] - 2025-01-25

### Fixed
- Critical bug where filestore was restored with source database name instead of target database name
- Filestore extraction now uses temporary directory to prevent data loss during restore
- Icons and attachments now correctly appear after restore due to proper filestore naming

### Changed
- Improved filestore restore process to rename directories during extraction
- Enhanced safety by extracting to temp directory before moving to final location

## [1.5.8] - 2025-01-25

### Added
- Post-restore cleanup to ensure icons are available
- Automatic cleanup of icon-related attachments that regenerate safely

## [1.5.4] - 2025-01-25

### Fixed
- PyPI publishing now uses correct version from __init__.py
- Centralized version management to prevent version mismatches

### Changed
- Dynamic version configuration in pyproject.toml
- GitHub Actions workflow triggers on tag push instead of release creation

## Previous Versions

See GitHub releases for older version history.