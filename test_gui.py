#!/usr/bin/env python3
"""Test that the GUI launches correctly"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import tkinter as tk
    from odoo_backup_tool.gui.main_window import OdooBackupRestoreGUI
    
    print("Creating GUI window...")
    root = tk.Tk()
    app = OdooBackupRestoreGUI(root)
    print("GUI created successfully! The window should be visible now.")
    print("Close the window to exit.")
    root.mainloop()
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()