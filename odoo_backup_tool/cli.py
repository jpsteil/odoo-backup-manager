#!/usr/bin/env python3
"""
Command-line interface for Odoo Backup Tool
"""

import sys
import argparse
import json
from pathlib import Path
import getpass

from .core.backup_restore import OdooBackupRestore
from .db.connection_manager import ConnectionManager
from .utils.config import Config


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Odoo Database and Filestore Backup/Restore Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Save a connection profile (do this first)
  odoo-backup connections save --name prod --host db.example.com --user odoo --database mydb --filestore /var/lib/odoo
  odoo-backup connections save --name dev --host localhost --user odoo --database devdb --allow-restore

  # Backup using connection profile
  odoo-backup backup --connection prod

  # Restore using connection profile
  odoo-backup restore --connection dev --file backup.tar.gz --name test_db

  # List saved connections
  odoo-backup connections list

  # Manual backup (without saved connection)
  odoo-backup backup --name mydb --host localhost --user odoo --filestore /var/lib/odoo/filestore

  # Manual restore (without saved connection)
  odoo-backup restore --file backup.tar.gz --name newdb --host localhost --user odoo
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create a backup")
    backup_parser.add_argument("--connection", "-c", help="Use saved connection profile (recommended)")
    backup_parser.add_argument("--name", help="Database name (required if not using connection)")
    backup_parser.add_argument("--host", default="localhost", help="Database host")
    backup_parser.add_argument("--port", type=int, default=5432, help="Database port")
    backup_parser.add_argument("--user", default="odoo", help="Database user")
    backup_parser.add_argument(
        "--password", help="Database password (will prompt if not provided)"
    )
    backup_parser.add_argument("--filestore", help="Filestore path")
    backup_parser.add_argument("--output-dir", help="Output directory for backup")
    backup_parser.add_argument(
        "--no-filestore", action="store_true", help="Skip filestore backup"
    )

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("--file", "-f", required=True, help="Backup file to restore")
    restore_parser.add_argument("--connection", "-c", help="Use saved connection profile (recommended)")
    restore_parser.add_argument("--name", help="Target database name (required if not using connection)")
    restore_parser.add_argument("--host", default="localhost", help="Database host")
    restore_parser.add_argument("--port", type=int, default=5432, help="Database port")
    restore_parser.add_argument("--user", default="odoo", help="Database user")
    restore_parser.add_argument(
        "--password", help="Database password (will prompt if not provided)"
    )
    restore_parser.add_argument("--filestore", help="Target filestore path")
    restore_parser.add_argument(
        "--no-filestore", action="store_true", help="Skip filestore restore"
    )
    restore_parser.add_argument(
        "--neutralize", action="store_true", 
        help="Neutralize database for testing (disable emails, reset passwords, etc.)"
    )

    # Connections management
    conn_parser = subparsers.add_parser("connections", help="Manage saved connections")
    conn_subparsers = conn_parser.add_subparsers(
        dest="conn_action", help="Connection actions"
    )

    # List connections
    conn_list = conn_subparsers.add_parser("list", help="List saved connections")

    # Save connection
    conn_save = conn_subparsers.add_parser("save", help="Save a new connection")
    conn_save.add_argument("--name", required=True, help="Connection name")
    conn_save.add_argument("--host", required=True, help="Database host")
    conn_save.add_argument("--port", type=int, default=5432, help="Database port")
    conn_save.add_argument("--database", help="Database name")
    conn_save.add_argument("--user", default="odoo", help="Database user")
    conn_save.add_argument("--password", help="Database password")
    conn_save.add_argument("--filestore", help="Filestore path")
    conn_save.add_argument("--odoo-version", default="17.0", help="Odoo version")
    conn_save.add_argument(
        "--allow-restore", action="store_true",
        help="Allow restore operations to this connection (use for dev/test only, not production)"
    )

    # Delete connection
    conn_delete = conn_subparsers.add_parser("delete", help="Delete a connection")
    conn_delete.add_argument("name", help="Connection name to delete")

    # Test connection
    conn_test = conn_subparsers.add_parser("test", help="Test a connection")
    conn_test.add_argument("name", help="Connection name to test")

    # Parse config file
    config_parser = subparsers.add_parser("from-config", help="Run from odoo.conf file")
    config_parser.add_argument("config_file", help="Path to odoo.conf file")
    config_parser.add_argument("--backup", action="store_true", help="Perform backup")
    config_parser.add_argument("--output-dir", help="Output directory for backup")

    # GUI command
    gui_parser = subparsers.add_parser("gui", help="Launch GUI interface")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Handle commands
    if args.command == "gui":
        launch_gui()
    elif args.command == "backup":
        handle_backup(args)
    elif args.command == "restore":
        handle_restore(args)
    elif args.command == "connections":
        handle_connections(args)
    elif args.command == "from-config":
        handle_from_config(args)
    else:
        parser.print_help()
        sys.exit(1)


def launch_gui():
    """Launch the GUI interface"""
    try:
        import tkinter as tk
        from .gui.main_window import OdooBackupRestoreGUI

        root = tk.Tk()
        app = OdooBackupRestoreGUI(root)
        root.mainloop()
    except ImportError as e:
        print("Error: GUI dependencies not available.")
        print("Please install tkinter: sudo apt-get install python3-tk")
        print(f"Error details: {e}")
        sys.exit(1)


def handle_backup(args):
    """Handle backup command"""
    conn_manager = ConnectionManager()
    config = Config()

    # Build configuration
    backup_config = {}

    if args.connection:
        # Load from saved connection (preferred method)
        connections = conn_manager.list_connections()
        conn = next((c for c in connections if c["name"] == args.connection), None)
        if not conn:
            print(f"Error: Connection '{args.connection}' not found")
            print("\nAvailable connections:")
            for c in connections:
                print(f"  - {c['name']}")
            print("\nUse 'odoo-backup connections save' to create a new connection")
            sys.exit(1)

        conn_data = conn_manager.get_odoo_connection(conn["id"])
        backup_config.update(
            {
                "db_name": args.name or conn_data["database"],  # Allow override with --name
                "db_host": conn_data["host"],
                "db_port": conn_data["port"],
                "db_user": conn_data["username"],
                "db_password": conn_data["password"],
                "filestore_path": conn_data["filestore_path"],
            }
        )
        
        if not backup_config["db_name"]:
            print("Error: Database name not specified. Use --name to specify the database to backup")
            sys.exit(1)
            
        print(f"Using connection: {args.connection}")
        print(f"Backing up database: {backup_config['db_name']}")
    else:
        # Manual configuration (backward compatibility)
        if not args.name:
            print("Error: Database name is required when not using a connection profile")
            print("Use --name to specify the database or --connection to use a saved profile")
            sys.exit(1)
            
        password = args.password
        if not password:
            password = getpass.getpass("Database password: ")

        backup_config = {
            "db_name": args.name,
            "db_host": args.host,
            "db_port": args.port,
            "db_user": args.user,
            "db_password": password,
            "filestore_path": args.filestore,
        }

    backup_config["backup_filestore"] = not args.no_filestore
    backup_config["backup_dir"] = args.output_dir or config.get_backup_dir()

    # Perform backup
    try:
        backup_restore = OdooBackupRestore()
        backup_file = backup_restore.backup(backup_config)
        print(f"✅ Backup completed successfully: {backup_file}")
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        sys.exit(1)


def handle_restore(args):
    """Handle restore command"""
    conn_manager = ConnectionManager()

    # Check if backup file exists
    if not Path(args.file).exists():
        print(f"Error: Backup file not found: {args.file}")
        sys.exit(1)

    # Build configuration
    restore_config = {}

    if args.connection:
        # Load from saved connection (preferred method)
        connections = conn_manager.list_connections()
        conn = next((c for c in connections if c["name"] == args.connection), None)
        if not conn:
            print(f"Error: Connection '{args.connection}' not found")
            print("\nAvailable connections:")
            for c in connections:
                print(f"  - {c['name']}")
            print("\nUse 'odoo-backup connections save' to create a new connection")
            sys.exit(1)

        conn_data = conn_manager.get_odoo_connection(conn["id"])
        
        # Check if restore is allowed for this connection
        if not conn_data.get('allow_restore', False):
            print(f"Error: Restore operations are not allowed for connection '{args.connection}'")
            print("This is a safety feature to prevent accidental restores to production databases.")
            print("To enable restore for this connection, edit it and enable the 'Allow Restore' option.")
            sys.exit(1)
            
        restore_config.update(
            {
                "db_name": args.name or conn_data["database"],  # Allow override with --name
                "db_host": conn_data["host"],
                "db_port": conn_data["port"],
                "db_user": conn_data["username"],
                "db_password": conn_data["password"],
                "filestore_path": conn_data["filestore_path"],
            }
        )
        
        if not restore_config["db_name"]:
            print("Error: Database name not specified. Use --name to specify the target database")
            sys.exit(1)
            
        print(f"Using connection: {args.connection}")
        print(f"Restoring to database: {restore_config['db_name']}")
    else:
        # Manual configuration (backward compatibility)
        if not args.name:
            print("Error: Database name is required when not using a connection profile")
            print("Use --name to specify the target database or --connection to use a saved profile")
            sys.exit(1)
            
        password = args.password
        if not password:
            password = getpass.getpass("Database password: ")

        restore_config = {
            "db_name": args.name,
            "db_host": args.host,
            "db_port": args.port,
            "db_user": args.user,
            "db_password": password,
            "filestore_path": args.filestore,
        }

    restore_config["restore_filestore"] = not args.no_filestore
    restore_config["neutralize"] = args.neutralize

    # Perform restore
    try:
        backup_restore = OdooBackupRestore()
        success = backup_restore.restore(restore_config, args.file)
        if success:
            print(f"✅ Restore completed successfully to database: {restore_config['db_name']}")
            if args.neutralize:
                print("🧪 Database has been neutralized for testing:")
                print("   - All outgoing mail servers disabled")
                print("   - All scheduled actions (crons) disabled")
                print("   - Admin password reset to 'admin'")
                print("   - All user passwords reset to 'demo'")
    except Exception as e:
        print(f"❌ Restore failed: {e}")
        sys.exit(1)


def handle_connections(args):
    """Handle connections management"""
    conn_manager = ConnectionManager()

    if args.conn_action == "list":
        connections = conn_manager.list_connections()
        if not connections:
            print("No saved connections found.")
        else:
            print("\nSaved Connections:")
            print("-" * 60)
            for conn in connections:
                # Get full connection details for Odoo connections
                if conn['type'] == 'odoo':
                    conn_data = conn_manager.get_odoo_connection(conn['id'])
                    allow_restore = conn_data.get('allow_restore', False)
                    restore_status = " ✅" if allow_restore else " 🔒"
                else:
                    restore_status = ""
                    
                print(f"  [{conn['type'].upper()}] {conn['name']}{restore_status}")
                print(f"    Host: {conn['host']}:{conn['port']}")
                if conn["type"] == "odoo" and conn.get("database"):
                    print(f"    Database: {conn['database']}")
                print(f"    User: {conn.get('username', 'N/A')}")
                print()

    elif args.conn_action == "save":
        password = args.password
        if password is None:
            password = getpass.getpass("Database password (optional): ")

        config = {
            "host": args.host,
            "port": args.port,
            "database": args.database,
            "username": args.user,
            "password": password if password else None,
            "filestore_path": args.filestore,
            "odoo_version": args.odoo_version,
            "allow_restore": args.allow_restore,
        }

        if conn_manager.save_odoo_connection(args.name, config):
            print(f"✅ Connection '{args.name}' saved successfully")
            if args.allow_restore:
                print("⚠️  Warning: Restore operations are enabled for this connection")
                print("   This should only be used for development/test databases")
            else:
                print("🔒 Restore operations are disabled (production safe)")
        else:
            print(f"❌ Failed to save connection '{args.name}'")

    elif args.conn_action == "delete":
        connections = conn_manager.list_connections()
        conn = next((c for c in connections if c["name"] == args.name), None)
        if not conn:
            print(f"Error: Connection '{args.name}' not found")
            sys.exit(1)

        if conn["type"] == "odoo":
            success = conn_manager.delete_odoo_connection(conn["id"])
        else:
            success = conn_manager.delete_ssh_connection(conn["id"])

        if success:
            print(f"✅ Connection '{args.name}' deleted successfully")
        else:
            print(f"❌ Failed to delete connection '{args.name}'")

    elif args.conn_action == "test":
        connections = conn_manager.list_connections()
        conn = next((c for c in connections if c["name"] == args.name), None)
        if not conn:
            print(f"Error: Connection '{args.name}' not found")
            sys.exit(1)

        if conn["type"] == "odoo":
            conn_data = conn_manager.get_odoo_connection(conn["id"])

            # Test connection
            backup_restore = OdooBackupRestore(conn_manager=conn_manager)
            test_config = {
                "db_name": conn_data["database"],
                "db_host": conn_data["host"],
                "db_port": conn_data["port"],
                "db_user": conn_data["username"],
                "db_password": conn_data["password"],
                "filestore_path": conn_data["filestore_path"],
            }

            success, message = backup_restore.test_connection(test_config)
            print(message)
            if success:
                print("✅ Connection test successful")
            else:
                print("❌ Connection test failed")
        else:
            print("Testing SSH connections not yet implemented")


def handle_from_config(args):
    """Handle operations from odoo.conf file"""
    try:
        # Parse the odoo.conf file
        config = OdooBackupRestore.parse_odoo_conf(args.config_file)

        print(f"Loaded configuration from: {args.config_file}")
        print(f"  Database: {config['database']}")
        print(f"  Host: {config['host']}:{config['port']}")
        print(f"  User: {config['username']}")
        print(f"  Filestore: {config['filestore_path']}")

        if args.backup:
            # Add output directory if specified
            if args.output_dir:
                config["backup_dir"] = args.output_dir
            else:
                app_config = Config()
                config["backup_dir"] = app_config.get_backup_dir()

            # Prompt for database name if not in config
            if not config["database"]:
                config["database"] = input("Enter database name to backup: ")

            config["db_name"] = config["database"]
            config["db_host"] = config["host"]
            config["db_port"] = config["port"]
            config["db_user"] = config["username"]
            config["db_password"] = config["password"]

            # Perform backup
            backup_restore = OdooBackupRestore()
            backup_file = backup_restore.backup(config)
            print(f"✅ Backup completed: {backup_file}")
        else:
            print("\nNo operation specified. Use --backup to create a backup.")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
