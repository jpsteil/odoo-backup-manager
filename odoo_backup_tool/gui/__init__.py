"""GUI module for Odoo Backup Tool"""

try:
    from .main_window import OdooBackupRestoreGUI

    __all__ = ["OdooBackupRestoreGUI"]
except ImportError:
    # GUI not available (tkinter not installed)
    __all__ = []
