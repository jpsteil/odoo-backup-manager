#!/usr/bin/env python3
"""
Migration script to add allow_restore column to existing database
"""

import sqlite3
from pathlib import Path

def migrate_database():
    """Add allow_restore column to odoo_connections table"""
    
    # Database path
    db_path = Path.home() / ".config" / "odoo_backup_tool" / "connections.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(odoo_connections)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'allow_restore' not in columns:
            print("Adding allow_restore column to odoo_connections table...")
            
            # Add the column with default value False (0)
            cursor.execute("""
                ALTER TABLE odoo_connections 
                ADD COLUMN allow_restore BOOLEAN DEFAULT 0
            """)
            
            # Set allow_restore=1 only for non-production databases
            # We'll be conservative and only enable for localhost and dev
            cursor.execute("""
                UPDATE odoo_connections 
                SET allow_restore = 1 
                WHERE LOWER(name) LIKE '%dev%' 
                   OR LOWER(name) LIKE '%test%' 
                   OR LOWER(name) = 'localhost'
                   OR LOWER(host) = 'localhost'
                   OR host = '127.0.0.1'
            """)
            
            conn.commit()
            
            # Show the results
            cursor.execute("SELECT name, host, database, allow_restore FROM odoo_connections")
            print("\nConnection restore permissions:")
            print("-" * 60)
            for row in cursor.fetchall():
                name, host, database, allow_restore = row
                status = "✓ ALLOWED" if allow_restore else "✗ PROTECTED"
                print(f"{name:20} {host:20} {database:20} {status}")
            
            print("\nMigration completed successfully!")
            print("Production databases are now protected from restore operations.")
        else:
            print("allow_restore column already exists")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        return False
    finally:
        conn.close()
    
    return True

if __name__ == "__main__":
    migrate_database()