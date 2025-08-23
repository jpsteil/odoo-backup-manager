#!/usr/bin/env python3
"""Test the restore protection mechanism"""

import sys
sys.path.insert(0, '.')

from odoo_backup_tool.db.connection_manager import ConnectionManager

# Initialize connection manager
conn_mgr = ConnectionManager()

# Get all connections
connections = conn_mgr.list_connections()

print("Connection Restore Permissions:")
print("-" * 60)

for conn in connections:
    if conn['type'] == 'odoo':
        allow_restore = conn.get('allow_restore', False)
        status = "✓ ALLOWED" if allow_restore else "✗ PROTECTED"
        print(f"{conn['name']:20} {conn['host']:20} {status}")

print("\nProtection Summary:")
odoo_conns = [c for c in connections if c['type'] == 'odoo']
allowed = [c for c in odoo_conns if c.get('allow_restore', False)]
protected = [c for c in odoo_conns if not c.get('allow_restore', False)]

print(f"  Total Odoo connections: {len(odoo_conns)}")
print(f"  Restore ALLOWED: {len(allowed)} ({', '.join([c['name'] for c in allowed])})")
print(f"  Restore PROTECTED: {len(protected)} ({', '.join([c['name'] for c in protected])})")