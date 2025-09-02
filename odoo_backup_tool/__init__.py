"""
Odoo Backup Tool - A comprehensive backup and restore utility for Odoo instances
"""

__version__ = "1.5.19"
__author__ = "Odoo Backup Tool Team"

from .core.backup_restore import OdooBackupRestore
from .db.connection_manager import ConnectionManager

__all__ = ["OdooBackupRestore", "ConnectionManager"]
