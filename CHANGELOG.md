# Changelog

All notable changes to this project will be documented in this file.

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