#!/usr/bin/env python3
"""
Version Manager Script
======================

This script helps manage version updates across the project.
It updates the version in the single source of truth (__init__.py)
and all other files will automatically use that version.

Usage:
    python version_manager.py current    # Show current version
    python version_manager.py set 1.6.0  # Set new version
"""

import sys
from pathlib import Path
import re

def get_current_version():
    """Get the current version from __init__.py"""
    version_file = Path("odoo_backup_tool") / "__init__.py"
    if not version_file.exists():
        raise RuntimeError("Cannot find odoo_backup_tool/__init__.py")
    
    version_content = version_file.read_text()
    for line in version_content.splitlines():
        if line.startswith('__version__'):
            if '"' in line:
                return line.split('"')[1]
            elif "'" in line:
                return line.split("'")[1]
    
    raise RuntimeError("Cannot find version in __init__.py")

def set_version(new_version):
    """Set a new version in __init__.py"""
    # Validate version format (basic check)
    if not re.match(r'^\d+\.\d+\.\d+$', new_version):
        raise ValueError(f"Version must be in format X.Y.Z, got: {new_version}")
    
    version_file = Path("odoo_backup_tool") / "__init__.py"
    if not version_file.exists():
        raise RuntimeError("Cannot find odoo_backup_tool/__init__.py")
    
    # Read current content
    content = version_file.read_text()
    lines = content.splitlines()
    
    # Replace the version line
    for i, line in enumerate(lines):
        if line.startswith('__version__'):
            if '"' in line:
                lines[i] = f'__version__ = "{new_version}"'
            elif "'" in line:
                lines[i] = f"__version__ = '{new_version}'"
            break
    else:
        raise RuntimeError("Cannot find __version__ line in __init__.py")
    
    # Write back to file
    version_file.write_text('\n'.join(lines) + '\n')
    print(f"Version updated to {new_version}")
    print("Files that will automatically use this version:")
    print("  - setup.py (via get_version())")
    print("  - pyproject.toml (via dynamic version)")
    print("  - GitHub workflows (via package import)")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "current":
        try:
            version = get_current_version()
            print(f"Current version: {version}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif command == "set":
        if len(sys.argv) != 3:
            print("Usage: python version_manager.py set <version>")
            print("Example: python version_manager.py set 1.6.0")
            sys.exit(1)
        
        new_version = sys.argv[2]
        try:
            old_version = get_current_version()
            set_version(new_version)
            print(f"Version changed from {old_version} to {new_version}")
            print("\nNext steps:")
            print(f"1. git add odoo_backup_tool/__init__.py")
            print(f"2. git commit -m 'Bump version to {new_version}'")
            print(f"3. git push origin main")
            print(f"4. git tag v{new_version}")
            print(f"5. git push origin v{new_version}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()