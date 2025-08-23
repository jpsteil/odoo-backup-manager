#!/usr/bin/env python3
"""
Simple test script to verify the package structure
"""

print("Testing package imports...")

try:
    # Test core imports
    from odoo_backup_tool import OdooBackupRestore, ConnectionManager
    print("✓ Core imports successful")
    
    # Test module imports
    from odoo_backup_tool.core.backup_restore import OdooBackupRestore
    print("✓ Core module import successful")
    
    from odoo_backup_tool.db.connection_manager import ConnectionManager
    print("✓ Database module import successful")
    
    from odoo_backup_tool.utils.config import Config
    print("✓ Utils module import successful")
    
    # Test instantiation
    conn_mgr = ConnectionManager()
    print("✓ ConnectionManager instantiation successful")
    
    config = Config()
    print("✓ Config instantiation successful")
    
    backup_restore = OdooBackupRestore()
    print("✓ OdooBackupRestore instantiation successful")
    
    # Test CLI import
    from odoo_backup_tool.cli import main
    print("✓ CLI import successful")
    
    print("\n✅ All tests passed! Package structure is correct.")
    
except ImportError as e:
    print(f"\n❌ Import error: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()