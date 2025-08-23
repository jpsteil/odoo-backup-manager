#!/usr/bin/env python3
"""Test the progress dialog implementation"""

import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, '.')
from odoo_backup_tool.gui.dialogs.progress_dialog import (
    ProgressDialog, SimpleProgressDialog, 
    TestConnectionDialog, BackupProgressDialog
)


def test_simple_operation(dialog):
    """Simple test operation"""
    for i in range(5):
        if dialog.cancelled:
            raise Exception("Operation cancelled by user")
        dialog.update_progress(i * 20, f"Processing step {i+1} of 5...")
        dialog.add_detail(f"Completed step {i+1}")
        time.sleep(1)
    dialog.update_progress(100, "Operation complete!")
    return "Success"


def test_connection_operation(dialog):
    """Test connection operation"""
    dialog.update_message("Establishing connection...")
    dialog.add_detail("Resolving hostname...")
    time.sleep(1)
    
    dialog.add_detail("Connecting to server...")
    time.sleep(1)
    
    dialog.add_detail("Authenticating...")
    time.sleep(1)
    
    dialog.add_detail("Testing database access...")
    time.sleep(1)
    
    dialog.update_message("Connection successful!")
    dialog.add_detail("✓ Connection test passed")
    return True


def test_backup_operation(dialog):
    """Test backup operation with progress"""
    total_steps = 10
    
    dialog.update_message("Preparing backup...")
    dialog.add_detail("Creating backup directory...")
    time.sleep(0.5)
    
    for i in range(total_steps):
        if dialog.cancelled:
            dialog.add_detail("Backup cancelled by user")
            raise Exception("Backup cancelled")
        
        progress = ((i + 1) / total_steps) * 100
        dialog.update_progress(progress, f"Backing up... ({i+1}/{total_steps})")
        dialog.add_detail(f"Backed up table_{i+1}")
        dialog.update_status(f"Files processed: {i+1}")
        time.sleep(0.5)
    
    dialog.update_message("Backup complete!")
    dialog.add_detail("✓ All data backed up successfully")
    return f"backup_{time.strftime('%Y%m%d_%H%M%S')}.tar.gz"


def main():
    """Test the progress dialogs"""
    root = tk.Tk()
    root.title("Progress Dialog Test")
    root.geometry("400x300")
    
    frame = ttk.Frame(root, padding="20")
    frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(frame, text="Progress Dialog Tests", 
             font=("TkDefaultFont", 14, "bold")).pack(pady=10)
    
    # Test 1: Simple progress dialog
    def test_simple():
        result, error = SimpleProgressDialog.show(
            root, 
            "Simple Operation",
            "Processing data...",
            test_simple_operation
        )
        if error:
            messagebox.showerror("Error", f"Operation failed: {error}")
        else:
            messagebox.showinfo("Success", f"Result: {result}")
    
    ttk.Button(frame, text="Test Simple Progress", 
              command=test_simple).pack(pady=5)
    
    # Test 2: Connection test dialog
    def test_connection():
        dialog = TestConnectionDialog(root, "production_db", test_connection_operation)
        result, error = dialog.wait_for_completion()
        if error:
            messagebox.showerror("Connection Failed", str(error))
        else:
            messagebox.showinfo("Connection Success", "Connection test passed!")
    
    ttk.Button(frame, text="Test Connection Dialog", 
              command=test_connection).pack(pady=5)
    
    # Test 3: Backup progress dialog
    def test_backup():
        dialog = BackupProgressDialog(root, "production_db", test_backup_operation)
        result, error = dialog.wait_for_completion()
        if error:
            messagebox.showerror("Backup Failed", str(error))
        else:
            messagebox.showinfo("Backup Complete", f"Backup saved as: {result}")
    
    ttk.Button(frame, text="Test Backup Progress", 
              command=test_backup).pack(pady=5)
    
    # Test 4: Custom progress dialog
    def test_custom():
        dialog = ProgressDialog(
            root,
            title="Custom Operation",
            message="Performing custom operation...",
            operation=None,  # We'll control it manually
            can_cancel=True,
            indeterminate=False
        )
        
        def run_custom():
            try:
                for i in range(101):
                    if dialog.cancelled:
                        raise Exception("Cancelled")
                    dialog.update_progress(i, f"Processing... {i}%")
                    if i % 10 == 0:
                        dialog.add_detail(f"Milestone: {i}% complete")
                    time.sleep(0.02)
                dialog.on_complete()
            except Exception as e:
                dialog.error = e
                dialog.on_error()
        
        import threading
        threading.Thread(target=run_custom, daemon=True).start()
    
    ttk.Button(frame, text="Test Custom Progress", 
              command=test_custom).pack(pady=5)
    
    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)
    
    ttk.Button(frame, text="Exit", command=root.quit).pack()
    
    root.mainloop()


if __name__ == "__main__":
    main()