"""
Odoo Backup Tool - A comprehensive backup and restore utility for Odoo instances
"""

__version__ = "1.5.22"
__author__ = "Odoo Backup Tool Team"

from .core.backup_restore import OdooBackupRestore
from .db.connection_manager import ConnectionManager
from .docker.exporter import DockerExporter

__all__ = ["OdooBackupRestore", "ConnectionManager", "DockerExporter"]
