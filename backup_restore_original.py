#!/usr/bin/env python3
"""
Odoo Database and Filestore Backup/Restore Tool with GUI and Connection Manager
This script handles complete backup and restoration of Odoo instances,
including PostgreSQL database and filestore data, with saved connection profiles.
"""

import os
import sys
import argparse
import subprocess
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
import json
import getpass
import threading
import queue
import sqlite3
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import hashlib
import configparser
import paramiko
from io import StringIO
import socket

# Try to import tkinter, but make it optional
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    print("Warning: tkinter not available. GUI mode disabled.")
    print("To install tkinter on Ubuntu/Debian: sudo apt-get install python3-tk")
    print("To install tkinter on RHEL/CentOS/Fedora: sudo dnf install python3-tkinter")
    print("Using CLI mode instead.\n")


class ConnectionManager:
    """Manage saved database connections with encrypted passwords"""

    def __init__(self, db_path=None):
        if db_path is None:
            # Store database in the same directory as this script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "odoo_backup_connections.db")
        self.db_path = db_path
        self.cipher_suite = self._get_cipher()
        self._init_db()

    def _get_cipher(self):
        """Create encryption cipher using machine-specific key"""
        # Use machine ID and username for key generation
        machine_id = str(os.getuid()) + os.path.expanduser("~")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"odoo_backup_salt_v1",
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
        return Fernet(key)

    def _init_db(self):
        """Initialize SQLite database with proper 3NF schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if we need to migrate from old single-table schema
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='connections'")
        old_table_exists = cursor.fetchone() is not None
        
        # Create SSH connections table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ssh_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 22,
                username TEXT NOT NULL,
                password TEXT,
                key_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Create Odoo connections table with foreign key to SSH connections
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS odoo_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 5432,
                database TEXT,
                username TEXT NOT NULL,
                password TEXT,
                filestore_path TEXT,
                odoo_version TEXT DEFAULT '17.0',
                is_local BOOLEAN DEFAULT 0,
                ssh_connection_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ssh_connection_id) REFERENCES ssh_connections(id) ON DELETE SET NULL
            )
            """
        )
        
        # Create settings table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # Migrate data from old schema if it exists
        if old_table_exists:
            cursor.execute("SELECT * FROM connections")
            old_connections = cursor.fetchall()
            
            # Get column names for mapping
            cursor.execute("PRAGMA table_info(connections)")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            for row in old_connections:
                # Create a dict for easier access
                conn_data = dict(zip(column_names, row))
                
                # Determine connection type
                conn_type = conn_data.get('connection_type', 'odoo')
                
                if conn_type == 'ssh':
                    # Migrate SSH connection
                    try:
                        cursor.execute(
                            """
                            INSERT INTO ssh_connections (name, host, port, username, password, key_path)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                conn_data.get('name'),
                                conn_data.get('host', conn_data.get('ssh_host', 'localhost')),
                                conn_data.get('port', conn_data.get('ssh_port', 22)),
                                conn_data.get('username', conn_data.get('ssh_user', '')),
                                conn_data.get('password', conn_data.get('ssh_password')),
                                conn_data.get('ssh_key_path', '')
                            )
                        )
                    except sqlite3.IntegrityError:
                        pass  # Skip duplicates
                else:
                    # Migrate Odoo connection
                    # First check if it references an SSH connection
                    ssh_conn_id = None
                    if conn_data.get('use_ssh') and conn_data.get('ssh_host'):
                        # Try to find matching SSH connection
                        cursor.execute(
                            "SELECT id FROM ssh_connections WHERE host = ? AND username = ?",
                            (conn_data.get('ssh_host'), conn_data.get('ssh_user', ''))
                        )
                        ssh_result = cursor.fetchone()
                        if ssh_result:
                            ssh_conn_id = ssh_result[0]
                    
                    try:
                        cursor.execute(
                            """
                            INSERT INTO odoo_connections 
                            (name, host, port, database, username, password, filestore_path, 
                             odoo_version, is_local, ssh_connection_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                conn_data.get('name'),
                                conn_data.get('host', 'localhost'),
                                conn_data.get('port', 5432),
                                conn_data.get('database', ''),
                                conn_data.get('username', 'odoo'),
                                conn_data.get('password'),
                                conn_data.get('filestore_path', ''),
                                conn_data.get('odoo_version', '17.0'),
                                conn_data.get('is_local', False),
                                ssh_conn_id
                            )
                        )
                    except sqlite3.IntegrityError:
                        pass  # Skip duplicates
            
            # Drop the old table after migration
            cursor.execute("DROP TABLE connections")
        
        conn.commit()
        conn.close()

    def save_ssh_connection(self, name, config):
        """Save an SSH connection profile"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Encrypt password if provided
        encrypted_password = None
        if config.get("password"):
            encrypted_password = self.cipher_suite.encrypt(
                config["password"].encode()
            ).decode()

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ssh_connections 
                (name, host, port, username, password, key_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    name,
                    config.get("host", "localhost"),
                    config.get("port", 22),
                    config.get("username", ""),
                    encrypted_password,
                    config.get("ssh_key_path", "")
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def save_odoo_connection(self, name, config):
        """Save an Odoo connection profile"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Encrypt password if provided
        encrypted_password = None
        if config.get("password"):
            encrypted_password = self.cipher_suite.encrypt(
                config["password"].encode()
            ).decode()
        
        # Get SSH connection ID if specified
        ssh_conn_id = None
        if config.get("ssh_connection_name"):
            cursor.execute(
                "SELECT id FROM ssh_connections WHERE name = ?",
                (config["ssh_connection_name"],)
            )
            result = cursor.fetchone()
            if result:
                ssh_conn_id = result[0]

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO odoo_connections 
                (name, host, port, database, username, password, filestore_path, 
                 odoo_version, is_local, ssh_connection_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    name,
                    config.get("host", "localhost"),
                    config.get("port", 5432),
                    config.get("database", ""),
                    config.get("username", "odoo"),
                    encrypted_password,
                    config.get("filestore_path", ""),
                    config.get("odoo_version", "17.0"),
                    config.get("is_local", False),
                    ssh_conn_id
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def save_connection(self, name, config):
        """Save a connection - routes to appropriate method based on type"""
        conn_type = config.get("connection_type", "odoo")
        if conn_type == "ssh":
            return self.save_ssh_connection(name, config)
        else:
            return self.save_odoo_connection(name, config)
    
    def update_ssh_connection(self, conn_id, name, config):
        """Update an SSH connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Encrypt password if provided
        encrypted_password = None
        if config.get("password"):
            encrypted_password = self.cipher_suite.encrypt(
                config["password"].encode()
            ).decode()

        try:
            cursor.execute(
                """
                UPDATE ssh_connections 
                SET name = ?, host = ?, port = ?, username = ?, password = ?, key_path = ?
                WHERE id = ?
            """,
                (
                    name,
                    config.get("host", "localhost"),
                    config.get("port", 22),
                    config.get("username", ""),
                    encrypted_password,
                    config.get("ssh_key_path", ""),
                    conn_id
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def update_odoo_connection(self, conn_id, name, config):
        """Update an Odoo connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Encrypt password if provided
        encrypted_password = None
        if config.get("password"):
            encrypted_password = self.cipher_suite.encrypt(
                config["password"].encode()
            ).decode()
        
        # SSH connection ID is passed directly now
        ssh_conn_id = config.get("ssh_connection_id")

        try:
            cursor.execute(
                """
                UPDATE odoo_connections 
                SET name = ?, host = ?, port = ?, database = ?, username = ?, 
                    password = ?, filestore_path = ?, odoo_version = ?, 
                    is_local = ?, ssh_connection_id = ?
                WHERE id = ?
            """,
                (
                    name,
                    config.get("host", "localhost"),
                    config.get("port", 5432),
                    config.get("database", ""),
                    config.get("username", "odoo"),
                    encrypted_password,
                    config.get("filestore_path", ""),
                    config.get("odoo_version", "17.0"),
                    config.get("is_local", False),
                    ssh_conn_id,
                    conn_id
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_ssh_connection(self, conn_id):
        """Get an SSH connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ssh_connections WHERE id = ?", (conn_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            config = {
                "id": row[0],
                "name": row[1],
                "host": row[2],
                "port": row[3],
                "username": row[4],
                "password": None,
                "ssh_key_path": row[6] if len(row) > 6 and row[6] else "",
                "connection_type": "ssh"
            }
            # Decrypt password
            if len(row) > 5 and row[5]:
                try:
                    config["password"] = self.cipher_suite.decrypt(row[5].encode()).decode()
                except:
                    pass
            return config
        return None
    
    def get_odoo_connection(self, conn_id):
        """Get an Odoo connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, s.name as ssh_name, s.host as ssh_host, s.port as ssh_port,
                   s.username as ssh_user, s.password as ssh_pass, s.key_path
            FROM odoo_connections o
            LEFT JOIN ssh_connections s ON o.ssh_connection_id = s.id
            WHERE o.id = ?
        """, (conn_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            config = {
                "id": row[0],
                "name": row[1],
                "host": row[2],
                "port": row[3],
                "database": row[4] if row[4] else "",
                "username": row[5],
                "password": None,
                "filestore_path": row[7] if row[7] else "",
                "odoo_version": row[8] if row[8] else "17.0",
                "is_local": row[9] if row[9] else False,
                "use_ssh": row[10] is not None,
                "ssh_connection_id": row[10] if row[10] else None,
                "ssh_connection_name": row[13] if row[10] and len(row) > 13 else "",
                "ssh_host": row[14] if row[10] and len(row) > 14 else "",
                "ssh_port": row[15] if row[10] and len(row) > 15 else 22,
                "ssh_user": row[16] if row[10] and len(row) > 16 else "",
                "ssh_password": None,
                "ssh_key_path": row[18] if row[10] and len(row) > 18 else "",
                "connection_type": "odoo"
            }
            
            # Decrypt Odoo password
            if row[6]:
                try:
                    config["password"] = self.cipher_suite.decrypt(row[6].encode()).decode()
                except:
                    pass
            
            # Decrypt SSH password if exists
            if row[10] and len(row) > 17 and row[17]:
                try:
                    config["ssh_password"] = self.cipher_suite.decrypt(row[17].encode()).decode()
                except:
                    pass
            
            return config
        return None

    def list_connections(self):
        """List all saved connections from both tables with IDs"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all connections with ID, name, and type info
        all_connections = []
        
        # Get SSH connections
        cursor.execute("SELECT id, name, host, port, username FROM ssh_connections ORDER BY name")
        for row in cursor.fetchall():
            all_connections.append({
                'id': row[0],
                'name': row[1],
                'host': row[2],
                'port': row[3],
                'username': row[4],
                'type': 'ssh'
            })
        
        # Get Odoo connections  
        cursor.execute("SELECT id, name, host, port, database, username FROM odoo_connections ORDER BY name")
        for row in cursor.fetchall():
            all_connections.append({
                'id': row[0],
                'name': row[1],
                'host': row[2],
                'port': row[3],
                'database': row[4],
                'username': row[5],
                'type': 'odoo'
            })
        
        conn.close()
        return all_connections

    def delete_ssh_connection(self, conn_id):
        """Delete an SSH connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ssh_connections WHERE id = ?", (conn_id,))
        conn.commit()
        affected = cursor.rowcount > 0
        conn.close()
        return affected
    
    def delete_odoo_connection(self, conn_id):
        """Delete an Odoo connection by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM odoo_connections WHERE id = ?", (conn_id,))
        conn.commit()
        affected = cursor.rowcount > 0
        conn.close()
        return affected
    
    def get_setting(self, key, default=None):
        """Get a setting value from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else default
    
    def set_setting(self, key, value):
        """Set a setting value in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (key, value)
        )
        conn.commit()
        conn.close()


class OdooBackupRestore:
    def __init__(self, progress_callback=None, log_callback=None, conn_manager=None):
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.temp_dir = tempfile.mkdtemp(prefix="odoo_backup_")
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.conn_manager = conn_manager
    
    @staticmethod
    def parse_odoo_conf(conf_path):
        """Parse odoo.conf file and extract connection settings"""
        if not os.path.exists(conf_path):
            raise FileNotFoundError(f"Config file not found: {conf_path}")
        
        config = configparser.ConfigParser()
        config.read(conf_path)
        
        # Get the main options section
        if 'options' not in config:
            raise ValueError("No 'options' section found in config file")
        
        options = config['options']
        
        # Extract connection details
        connection_config = {
            'host': options.get('db_host', 'localhost'),
            'port': options.get('db_port', '5432'),
            'database': options.get('db_name', 'False'),  # Odoo uses 'False' as default
            'username': options.get('db_user', 'odoo'),
            'password': options.get('db_password', 'False'),
            'filestore_path': None,
            'odoo_version': '17.0',  # Default version
            'is_local': options.get('db_host', 'localhost') in ['localhost', '127.0.0.1']
        }
        
        # Try to determine filestore path
        data_dir = options.get('data_dir', None)
        if data_dir and data_dir != 'False':
            # If data_dir is specified, use it as the base filestore path
            # The user should provide the full path to where filestore is located
            connection_config['filestore_path'] = data_dir
        else:
            # Default Odoo filestore location 
            # User should adjust this path as needed
            connection_config['filestore_path'] = os.path.expanduser("~/.local/share/Odoo")
        
        # Clean up 'False' values
        for key in ['database', 'password']:
            if connection_config[key] == 'False':
                connection_config[key] = ''
        
        return connection_config

    def __del__(self):
        # Cleanup temp directory
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def log(self, message, level="info"):
        """Log message with callback support"""
        print(message)
        if self.log_callback:
            self.log_callback(message, level)
    
    def _log(self, message, level="info"):
        """Internal log method (alias for log)"""
        self.log(message, level)

    def update_progress(self, value, message=""):
        """Update progress with callback support"""
        if self.progress_callback:
            self.progress_callback(value, message)

    def run_command(self, command, shell=False, capture_output=True):
        """Execute shell command and return output"""
        try:
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=capture_output,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            self.log(f"Error executing command: {e}", "error")
            self.log(f"Error output: {e.stderr}", "error")
            raise

    def check_dependencies(self):
        """Check if required tools are installed"""
        dependencies = ["pg_dump", "pg_restore", "psql", "tar"]
        missing = []

        for dep in dependencies:
            if shutil.which(dep) is None:
                missing.append(dep)

        if missing:
            error_msg = f"Missing dependencies: {', '.join(missing)}\nPlease install PostgreSQL client tools and tar"
            self.log(error_msg, "error")
            raise Exception(error_msg)

    def test_connection(self, config):
        """Test database connection and filestore path"""
        messages = []
        has_errors = False
        
        # Test database connection
        env = os.environ.copy()
        if config.get("db_password"):
            env["PGPASSWORD"] = config["db_password"]

        try:
            cmd = [
                "psql",
                "-h",
                config["db_host"],
                "-p",
                str(config["db_port"]),
                "-U",
                config["db_user"],
                "-d",
                "postgres",
                "-c",
                "SELECT version();",
            ]

            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                messages.append("✓ Database connection successful")
            else:
                messages.append(f"✗ Database connection failed: {result.stderr}")
                has_errors = True
                
        except Exception as e:
            messages.append(f"✗ Database connection error: {str(e)}")
            has_errors = True
        
        # Test filestore path if provided
        filestore_path = config.get("filestore_path")
        if filestore_path:
            # Check if using SSH
            if config.get("use_ssh") and config.get("ssh_connection_id"):
                # Test remote filestore path
                try:
                    ssh_conn = self.conn_manager.get_ssh_connection(config["ssh_connection_id"])
                    if ssh_conn:
                        import paramiko
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        
                        connect_kwargs = {
                            "hostname": ssh_conn["host"],
                            "port": ssh_conn.get("port", 22),
                            "username": ssh_conn["username"],
                        }
                        
                        if ssh_conn.get("key_path"):
                            connect_kwargs["key_filename"] = ssh_conn["key_path"]
                        elif ssh_conn.get("password"):
                            connect_kwargs["password"] = ssh_conn["password"]
                        
                        ssh.connect(**connect_kwargs)
                        
                        # Check if the filestore path exists
                        stdin, stdout, stderr = ssh.exec_command(f"test -d '{filestore_path}'")
                        if stdout.channel.recv_exit_status() == 0:
                            messages.append(f"✓ Remote filestore path exists: {filestore_path}")
                        else:
                            # Try with database name appended
                            db_name = config.get("db_name", "")
                            if db_name:
                                full_path = os.path.join(filestore_path, "filestore", db_name)
                                stdin, stdout, stderr = ssh.exec_command(f"test -d '{full_path}'")
                                if stdout.channel.recv_exit_status() == 0:
                                    messages.append(f"✓ Remote filestore path exists: {full_path}")
                                else:
                                    messages.append(f"⚠ Remote filestore path not found: {filestore_path} or {full_path}")
                            else:
                                messages.append(f"⚠ Remote filestore path not found: {filestore_path}")
                        
                        ssh.close()
                    else:
                        messages.append("⚠ SSH connection not found for filestore test")
                except Exception as e:
                    messages.append(f"⚠ Could not test remote filestore: {str(e)}")
            else:
                # Test local filestore path
                if os.path.exists(filestore_path):
                    messages.append(f"✓ Local filestore path exists: {filestore_path}")
                else:
                    # Try with database name appended
                    db_name = config.get("db_name", "")
                    if db_name:
                        full_path = os.path.join(filestore_path, "filestore", db_name)
                        if os.path.exists(full_path):
                            messages.append(f"✓ Local filestore path exists: {full_path}")
                        else:
                            messages.append(f"⚠ Local filestore path not found: {filestore_path} or {full_path}")
                    else:
                        messages.append(f"⚠ Local filestore path not found: {filestore_path}")
        
        # Return combined result
        return not has_errors, "\n".join(messages)

    def check_remote_disk_space(self, ssh, path, estimated_size_mb):
        """Check if remote server has enough disk space for backup"""
        try:
            # Get available space in /tmp
            stdin, stdout, stderr = ssh.exec_command("df -BM /tmp | tail -1 | awk '{print $4}'")
            available_space = stdout.read().decode().strip()
            # Remove 'M' suffix and convert to integer
            available_mb = int(available_space.rstrip('M'))
            
            # Add 20% safety margin to estimated size
            required_mb = int(estimated_size_mb * 1.2)
            
            if available_mb < required_mb:
                return False, available_mb, required_mb
            return True, available_mb, required_mb
        except Exception as e:
            self.log(f"Warning: Could not check disk space: {e}", "warning")
            return True, 0, 0  # Proceed anyway if check fails
    
    def estimate_compressed_size(self, ssh, path, is_database=False):
        """Estimate compressed size of a directory or database"""
        try:
            if is_database:
                # For database, get the database size from PostgreSQL
                return 100  # Default estimate for database
            else:
                # For filestore, get directory size
                stdin, stdout, stderr = ssh.exec_command(f"du -sm '{path}' | cut -f1")
                size_mb = int(stdout.read().decode().strip())
                # Estimate compression ratio (typically 30-50% for filestore)
                compressed_estimate = size_mb * 0.4
                return compressed_estimate
        except Exception as e:
            self.log(f"Warning: Could not estimate size: {e}", "warning")
            return 100  # Default conservative estimate

    def backup_database(self, config):
        """Backup PostgreSQL database"""
        self.log(f"Backing up database: {config['db_name']}...")
        self.update_progress(20, "Backing up database...")

        # Build pg_dump command
        dump_file = os.path.join(self.temp_dir, f"{config['db_name']}.sql")

        env = os.environ.copy()
        if config.get("db_password"):
            env["PGPASSWORD"] = config["db_password"]

        cmd = [
            "pg_dump",
            "-h",
            config["db_host"],
            "-p",
            str(config["db_port"]),
            "-U",
            config["db_user"],
            "-d",
            config["db_name"],
            "-f",
            dump_file,
            "--no-owner",
            "--no-acl",
        ]

        if config.get("verbose"):
            cmd.append("-v")

        subprocess.run(cmd, env=env, check=True)
        self.log(f"Database backed up successfully")
        self.update_progress(40, "Database backup complete")
        return dump_file

    def backup_filestore(self, config):
        """Backup Odoo filestore"""
        filestore_path = config["filestore_path"]
        
        if not filestore_path:
            self.log("Warning: Filestore path not specified", "warning")
            return None

        # Check if we need to use SSH
        if config.get("use_ssh") and config.get("ssh_connection_id"):
            # Get SSH connection details
            ssh_conn = self.conn_manager.get_ssh_connection(config["ssh_connection_id"])
            if not ssh_conn:
                self.log("Error: SSH connection not found", "error")
                return None
            
            self.log(f"Backing up remote filestore via SSH: {filestore_path}...")
            self.update_progress(50, "Backing up remote filestore...")
            
            try:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Connect to SSH
                connect_kwargs = {
                    "hostname": ssh_conn["host"],
                    "port": ssh_conn.get("port", 22),
                    "username": ssh_conn["username"],
                }
                
                if ssh_conn.get("key_path"):
                    connect_kwargs["key_filename"] = ssh_conn["key_path"]
                elif ssh_conn.get("password"):
                    connect_kwargs["password"] = ssh_conn["password"]
                
                ssh.connect(**connect_kwargs)
                
                # Create remote tar archive
                archive_name = os.path.join(self.temp_dir, "filestore.tar.gz")
                remote_temp = f"/tmp/filestore_{self.timestamp}.tar.gz"
                
                # Create tar on remote server
                # For Odoo, the filestore path should include the database name subdirectory
                # Check if the path exists first, if not try appending the database name
                self.log("Checking remote filestore path...")
                
                # First check if the path exists as-is
                stdin, stdout, stderr = ssh.exec_command(f"test -d '{filestore_path}'")
                if stdout.channel.recv_exit_status() != 0:
                    # Path doesn't exist, try with database name appended
                    db_name = config.get("db_name", "")
                    if db_name:
                        filestore_path = os.path.join(filestore_path, "filestore", db_name)
                        self.log(f"Adjusted filestore path to: {filestore_path}")
                
                # Estimate compressed size
                self.log("Estimating backup size...")
                estimated_size = self.estimate_compressed_size(ssh, filestore_path, is_database=False)
                
                # Check disk space
                has_space, available_mb, required_mb = self.check_remote_disk_space(ssh, "/tmp", estimated_size)
                
                if not has_space:
                    error_msg = f"Insufficient disk space on remote server!\n"
                    error_msg += f"Available: {available_mb}MB, Required: {required_mb}MB\n"
                    error_msg += f"Please free up space in /tmp on the remote server."
                    self.log(error_msg, "error")
                    ssh.close()
                    raise Exception(error_msg)
                
                self.log(f"Disk space check passed (Available: {available_mb}MB, Required: {required_mb}MB)")
                self.log("Creating remote archive...")
                
                stdin, stdout, stderr = ssh.exec_command(
                    f"cd '{filestore_path}' && tar -czf {remote_temp} ."
                )
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    self.log(f"Error creating remote archive: {error_msg}", "error")
                    ssh.close()
                    return None
                
                try:
                    # Download the archive via SFTP
                    self.log("Downloading filestore archive...")
                    sftp = ssh.open_sftp()
                    sftp.get(remote_temp, archive_name)
                    sftp.close()
                    
                    self.log("Remote filestore backed up successfully")
                    self.update_progress(70, "Filestore backup complete")
                    return archive_name
                    
                finally:
                    # Always clean up remote temp file, even if download fails
                    self.log("Cleaning up remote temporary files...")
                    ssh.exec_command(f"rm -f {remote_temp}")
                    ssh.close()
                
            except Exception as e:
                self.log(f"Error backing up remote filestore: {str(e)}", "error")
                return None
        else:
            # Local filestore backup
            if not os.path.exists(filestore_path):
                self.log(
                    f"Warning: Local filestore path does not exist: {filestore_path}",
                    "warning",
                )
                return None
            
            self.log(f"Backing up local filestore: {filestore_path}...")
            self.update_progress(50, "Backing up filestore...")

            # Create tar archive of filestore
            archive_name = os.path.join(self.temp_dir, "filestore.tar.gz")
            with tarfile.open(archive_name, "w:gz") as tar:
                tar.add(filestore_path, arcname="filestore")

            self.log(f"Filestore backed up successfully")
            self.update_progress(70, "Filestore backup complete")
            return archive_name

    def create_backup_archive(self, config, db_dump, filestore_archive):
        """Create combined backup archive"""
        backup_name = f"odoo_backup_{config['db_name']}_{self.timestamp}.tar.gz"
        backup_path = os.path.join(config.get("backup_dir", self.temp_dir), backup_name)

        self.log(f"Creating backup archive: {backup_name}...")
        self.update_progress(80, "Creating archive...")

        # Create metadata file
        metadata = {
            "timestamp": self.timestamp,
            "db_name": config["db_name"],
            "odoo_version": config.get("odoo_version", "unknown"),
            "has_filestore": filestore_archive is not None,
        }

        metadata_file = os.path.join(self.temp_dir, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Create combined archive
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(db_dump, arcname=os.path.basename(db_dump))
            tar.add(metadata_file, arcname="metadata.json")
            if filestore_archive:
                tar.add(filestore_archive, arcname=os.path.basename(filestore_archive))

        self.log(f"✅ Backup complete: {backup_path}", "success")
        self.update_progress(90, "Backup archive created")
        return backup_path

    def extract_backup(self, backup_file):
        """Extract backup archive"""
        self.log(f"Extracting backup: {os.path.basename(backup_file)}...")
        self.update_progress(10, "Extracting backup...")

        extract_dir = os.path.join(self.temp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)

        # Try to detect actual file type regardless of extension
        import zipfile
        
        # First try as zip (since some .tar.gz files might actually be zips)
        try:
            with zipfile.ZipFile(backup_file, 'r') as zf:
                self.log("Detected ZIP format, extracting...")
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            # Not a zip, try tar.gz
            try:
                with tarfile.open(backup_file, "r:gz") as tar:
                    self.log("Detected TAR.GZ format, extracting...")
                    tar.extractall(extract_dir)
            except tarfile.ReadError:
                # Try regular tar
                try:
                    with tarfile.open(backup_file, "r") as tar:
                        self.log("Detected TAR format, extracting...")
                        tar.extractall(extract_dir)
                except:
                    raise Exception(f"Unable to extract {backup_file}. File format not recognized. Tried ZIP, TAR.GZ, and TAR formats.")

        # Read metadata
        metadata_file = os.path.join(extract_dir, "metadata.json")
        if os.path.exists(metadata_file):
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
        else:
            metadata = {}

        # Find files
        files = os.listdir(extract_dir)
        db_dump = None
        filestore_archive = None

        for file in files:
            if file.endswith(".sql"):
                db_dump = os.path.join(extract_dir, file)
            elif file == "filestore.tar.gz":
                filestore_archive = os.path.join(extract_dir, file)

        self.update_progress(20, "Backup extracted")
        return db_dump, filestore_archive, metadata

    def restore_database(self, config, db_dump):
        """Restore PostgreSQL database"""
        try:
            self.log(f"Restoring database: {config['db_name']}...")
            self.update_progress(30, "Restoring database...")

            env = os.environ.copy()
            if config.get("db_password"):
                env["PGPASSWORD"] = config["db_password"]

            # Check if database exists
            check_cmd = [
                "psql",
                "-h",
                config["db_host"],
                "-p",
                str(config["db_port"]),
                "-U",
                config["db_user"],
                "-lqt",
            ]

            result = subprocess.run(check_cmd, env=env, capture_output=True, text=True)
            db_exists = config["db_name"] in result.stdout

            if db_exists:
                # Always drop and recreate the database
                self.log(f"Dropping existing database: {config['db_name']}...")
                # Terminate connections
                terminate_cmd = f"""
                    SELECT pg_terminate_backend(pid) 
                    FROM pg_stat_activity 
                    WHERE datname = '{config['db_name']}' AND pid <> pg_backend_pid();
                """
                subprocess.run(
                    [
                        "psql",
                        "-h",
                        config["db_host"],
                        "-p",
                        str(config["db_port"]),
                        "-U",
                        config["db_user"],
                        "-d",
                        "postgres",
                        "-c",
                        terminate_cmd,
                    ],
                    env=env,
                    capture_output=True,
                )

                # Drop database
                drop_cmd = [
                    "dropdb",
                    "-h",
                    config["db_host"],
                    "-p",
                    str(config["db_port"]),
                    "-U",
                    config["db_user"],
                    config["db_name"],
                ]
                subprocess.run(drop_cmd, env=env, check=True)

            # Create database
            self.log(f"Creating database: {config['db_name']}...")
            create_cmd = [
                "createdb",
                "-h",
                config["db_host"],
                "-p",
                str(config["db_port"]),
                "-U",
                config["db_user"],
                config["db_name"],
            ]
            subprocess.run(create_cmd, env=env, check=True)

            # Restore database
            self.update_progress(50, "Importing database data...")
            
            # Check if db_dump is a file path or bytes
            if isinstance(db_dump, str) and os.path.exists(db_dump):
                # It's a file path, use -f flag
                restore_cmd = [
                    "psql",
                    "-h",
                    config["db_host"],
                    "-p",
                    str(config["db_port"]),
                    "-U",
                    config["db_user"],
                    "-d",
                    config["db_name"],
                    "-f",
                    db_dump,
                ]
                if not config.get("verbose"):
                    restore_cmd.extend(["-q"])
                subprocess.run(restore_cmd, env=env, check=True)
                
                self.log(f"Database restored successfully")
                self.update_progress(70, "Database restore complete")
                return True
                
            else:
                # It's bytes data, pipe through stdin
                restore_cmd = [
                    "psql",
                    "-h",
                    config["db_host"],
                    "-p",
                    str(config["db_port"]),
                    "-U",
                    config["db_user"],
                    "-d",
                    config["db_name"],
                ]
                if not config.get("verbose"):
                    restore_cmd.extend(["-q"])
                
                # If db_dump is bytes, use it directly. If it's a string path, read the file
                if isinstance(db_dump, bytes):
                    input_data = db_dump
                else:
                    with open(db_dump, 'rb') as f:
                        input_data = f.read()
                
                subprocess.run(restore_cmd, env=env, input=input_data, check=True)
                
                self.log(f"Database restored successfully")
                self.update_progress(70, "Database restore complete")
                return True
            
        except subprocess.CalledProcessError as e:
            self.log(f"Database restore failed: {str(e)}", "error")
            return False
        except Exception as e:
            self.log(f"Database restore error: {str(e)}", "error")
            return False

    def restore_filestore(self, config, filestore_archive):
        """Restore Odoo filestore"""
        if not filestore_archive:
            self.log("No filestore archive found in backup", "warning")
            return

        # Construct the full filestore path for this database
        base_path = config["filestore_path"]
        db_name = config["db_name"]
        
        # Check if the path already includes 'filestore' and the database name
        if base_path.endswith(db_name):
            # Path already includes database name
            filestore_path = base_path
        elif 'filestore' in base_path:
            # Path includes filestore but not database name
            filestore_path = os.path.join(base_path, db_name)
        else:
            # Path is the base directory, add filestore/db_name
            filestore_path = os.path.join(base_path, "filestore", db_name)
        
        self.log(f"Restoring filestore to: {filestore_path}...")
        self.update_progress(80, "Restoring filestore...")

        # Backup existing filestore if it exists
        if os.path.exists(filestore_path):
            # Always backup and replace existing filestore
            backup_path = f"{filestore_path}.bak.{self.timestamp}"
            self.log(f"Moving existing filestore to: {backup_path}")
            shutil.move(filestore_path, backup_path)

        # Create the target filestore directory
        parent_dir = os.path.dirname(filestore_path)
        os.makedirs(parent_dir, exist_ok=True)
        os.makedirs(filestore_path, exist_ok=True)
        
        # Extract directly to the filestore path
        with tarfile.open(filestore_archive, "r:gz") as tar:
            tar.extractall(filestore_path)

        self.log(f"Filestore restored successfully")
        self.update_progress(95, "Filestore restore complete")
        return True

    def backup(self, config):
        """Create a complete backup (database + filestore) and return the zip file path"""
        try:
            self._log(f"Starting backup of {config['db_name']}...", "info")
            
            # Create temp directory for this backup
            backup_dir = os.path.join(self.temp_dir, f"backup_{config['db_name']}_{self.timestamp}")
            os.makedirs(backup_dir, exist_ok=True)
            
            # Backup database
            if not config.get('filestore_only', False):
                self._log("Backing up database...", "info")
                db_dump_file = self.backup_database(config)
                if db_dump_file:
                    # Read the dump file and save to backup dir
                    db_path = os.path.join(backup_dir, "database.sql")
                    with open(db_dump_file, 'rb') as src:
                        with open(db_path, 'wb') as dst:
                            dst.write(src.read())
                    self._log("Database backup completed", "success")
                else:
                    self._log("Database backup failed", "error")
                    return None
            
            # Backup filestore
            if not config.get('db_only', False) and config.get('filestore_path'):
                self._log("Backing up filestore...", "info")
                filestore_archive = self.backup_filestore(config)
                if filestore_archive:
                    # Read the filestore archive and save to backup dir
                    filestore_path = os.path.join(backup_dir, "filestore.tar.gz")
                    with open(filestore_archive, 'rb') as src:
                        with open(filestore_path, 'wb') as dst:
                            dst.write(src.read())
                    self._log("Filestore backup completed", "success")
            
            # Create final zip archive
            zip_path = os.path.join(self.temp_dir, f"{config['db_name']}_backup_{self.timestamp}.zip")
            self._log(f"Creating archive: {zip_path}", "info")
            
            import zipfile
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(backup_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, backup_dir)
                        zipf.write(file_path, arcname)
            
            self._log(f"Backup completed: {zip_path}", "success")
            return zip_path
            
        except Exception as e:
            self._log(f"Backup failed: {str(e)}", "error")
            return None
    
    def restore(self, config, backup_file):
        """Restore from a backup archive file"""
        try:
            
            # Extract backup archive
            extract_dir = os.path.join(self.temp_dir, f"restore_{self.timestamp}")
            os.makedirs(extract_dir, exist_ok=True)
            
            # Try to detect actual file type regardless of extension
            import zipfile
            import tarfile
            
            # First try as zip (since some .tar.gz files might actually be zips)
            try:
                with zipfile.ZipFile(backup_file, 'r') as zipf:
                    self._log("Detected ZIP format, extracting...", "info")
                    zipf.extractall(extract_dir)
            except zipfile.BadZipFile:
                # Not a zip, try tar.gz
                try:
                    with tarfile.open(backup_file, 'r:gz') as tar:
                        self._log("Detected TAR.GZ format, extracting...", "info")
                        tar.extractall(extract_dir)
                except tarfile.ReadError:
                    # Try regular tar
                    try:
                        with tarfile.open(backup_file, 'r') as tar:
                            self._log("Detected TAR format, extracting...", "info")
                            tar.extractall(extract_dir)
                    except Exception as e:
                        raise Exception(f"Unable to extract {backup_file}. File format not recognized. Tried ZIP, TAR.GZ, and TAR formats.")
            
            # Check what's in the backup
            has_database = os.path.exists(os.path.join(extract_dir, "database.sql"))
            has_filestore = os.path.exists(os.path.join(extract_dir, "filestore.tar.gz"))
            
            # Restore database
            if has_database and not config.get('filestore_only', False):
                self._log("Restoring database...", "info")
                # Pass the file path directly instead of reading into memory
                db_dump_path = os.path.join(extract_dir, "database.sql")
                success = self.restore_database(config, db_dump_path)
                if not success:
                    self._log("Database restore failed", "error")
                    return False
            
            # Restore filestore
            if has_filestore and not config.get('db_only', False) and config.get('filestore_path'):
                self._log("Restoring filestore...", "info")
                # Pass the file path directly instead of reading into memory
                filestore_archive_path = os.path.join(extract_dir, "filestore.tar.gz")
                success = self.restore_filestore(config, filestore_archive_path)
                if not success:
                    self._log("Filestore restore failed", "error")
                    return False
            
            return True
            
        except Exception as e:
            self._log(f"Restore failed: {str(e)}", "error")
            return False

    def backup_and_restore(self, source_config, dest_config):
        """Perform backup from source and restore to destination in one operation"""
        self.update_progress(0, "Starting backup and restore...")

        try:
            # Step 1: Backup from source
            self.log("=== BACKING UP FROM SOURCE ===", "info")
            self.log(
                f"Source: {source_config['db_host']}:{source_config['db_port']}/{source_config['db_name']}"
            )

            # Test source connection
            success, msg = self.test_connection(source_config)
            if not success:
                raise Exception(f"Source connection failed: {msg}")

            # Perform backup
            db_dump = self.backup_database(source_config)
            filestore_archive = None

            if not source_config.get("db_only") and source_config.get("filestore_path"):
                filestore_archive = self.backup_filestore(source_config)

            # Step 2: Restore to destination
            self.log("\n=== RESTORING TO DESTINATION ===", "info")
            self.log(
                f"Destination: {dest_config['db_host']}:{dest_config['db_port']}/{dest_config['db_name']}"
            )

            # Test destination connection
            success, msg = self.test_connection(dest_config)
            if not success:
                raise Exception(f"Destination connection failed: {msg}")

            # Restore database
            if not dest_config.get("filestore_only"):
                self.restore_database(dest_config, db_dump)

            # Restore filestore
            if (
                not dest_config.get("db_only")
                and filestore_archive
                and dest_config.get("filestore_path")
            ):
                self.restore_filestore(dest_config, filestore_archive)

            # Optionally save backup archive
            if source_config.get("save_backup"):
                backup_file = self.create_backup_archive(
                    source_config, db_dump, filestore_archive
                )
                self.log(f"\n📦 Backup saved to: {backup_file}", "success")

            self.log(f"\n✅ Backup and restore completed successfully!", "success")
            self.update_progress(100, "Complete!")

            return True

        except Exception as e:
            self.log(f"\n❌ Operation failed: {str(e)}", "error")
            raise


class OdooBackupRestoreGUI:
    """GUI interface for Odoo Backup/Restore - only loaded if tkinter is available"""

    def __init__(self, root):
        self.root = root
        self.root.title("Odoo Backup & Restore Tool with Connection Manager")
        # Let tkinter auto-size the window based on content
        # Set minimum size to prevent window from being too small
        self.root.minsize(800, 600)
        # Optional: Set maximum size if needed
        # self.root.maxsize(1400, 900)

        # Set style
        style = ttk.Style()
        style.theme_use("clam")

        # Initialize connection manager
        self.conn_manager = ConnectionManager()
        
        # Load configuration from database
        self.load_config()

        # Variables
        self.source_conn = tk.StringVar()
        self.dest_conn = tk.StringVar()
        self.save_backup = tk.BooleanVar(value=False)
        self.backup_dir_path = tk.StringVar(value=self.backup_directory)

        # Create notebook for tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # Create tabs
        self.create_backup_restore_tab()
        self.create_backup_files_tab()
        self.create_connections_tab()
        
        # Auto-size window to content after all widgets are created
        self.auto_size_window()
    
    def auto_size_window(self):
        """Auto-size the window to fit its content nicely"""
        # Update the window to calculate widget sizes
        self.root.update_idletasks()
        
        # Get the required size based on content
        req_width = self.root.winfo_reqwidth()
        req_height = self.root.winfo_reqheight()
        
        # Add minimal padding for a snug fit
        width = max(req_width + 20, 900)  # Min 900 width
        height = max(req_height + 20, 650)  # Min 650 height
        
        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Center the window on screen
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        # Set the geometry
        self.root.geometry(f"{width}x{height}+{x}+{y}")
    
    def load_config(self):
        """Load configuration from database"""
        # Get backup directory from database, default to current directory
        self.backup_directory = self.conn_manager.get_setting('backup_directory', os.getcwd())
        
        # Ensure the directory exists
        if not os.path.exists(self.backup_directory):
            try:
                os.makedirs(self.backup_directory, exist_ok=True)
            except:
                # If can't create, fall back to current directory
                self.backup_directory = os.getcwd()
                self.conn_manager.set_setting('backup_directory', self.backup_directory)
    
    def save_config(self):
        """Save configuration to database"""
        try:
            self.conn_manager.set_setting('backup_directory', self.backup_directory)
        except Exception as e:
            print(f"Error saving config: {e}")

    def create_backup_restore_tab(self):
        """Create the main backup/restore tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Backup & Restore")

        # Create main container - don't expand vertically
        main_container = ttk.Frame(tab, padding="10")
        main_container.pack(fill="both", expand=False, anchor="n")

        # Operation Mode (moved to top)
        self.mode_frame = ttk.LabelFrame(main_container, text="Operation Mode", padding="10")
        self.mode_frame.pack(fill="x", pady=5)
        
        self.operation_mode = tk.StringVar(value="backup_restore")
        
        # Radio buttons for operation mode
        mode_options_frame = ttk.Frame(self.mode_frame)
        mode_options_frame.pack(side="left")
        
        ttk.Radiobutton(
            mode_options_frame, text="Backup & Restore", 
            variable=self.operation_mode, value="backup_restore",
            command=self.update_operation_ui
        ).pack(side="left", padx=10)
        ttk.Radiobutton(
            mode_options_frame, text="Backup Only", 
            variable=self.operation_mode, value="backup_only",
            command=self.update_operation_ui
        ).pack(side="left", padx=10)
        ttk.Radiobutton(
            mode_options_frame, text="Restore Only", 
            variable=self.operation_mode, value="restore_only",
            command=self.update_operation_ui
        ).pack(side="left", padx=10)
        
        # Backup/Restore file options (initially hidden)
        self.file_options_frame = ttk.Frame(self.mode_frame)
        self.file_options_frame.pack(side="left", padx=20)
        
        # For backup only - where to save
        self.backup_file_frame = ttk.Frame(self.file_options_frame)
        self.backup_file_var = tk.StringVar()
        ttk.Label(self.backup_file_frame, text="Save to:").pack(side="left", padx=5)
        ttk.Entry(self.backup_file_frame, textvariable=self.backup_file_var, width=40).pack(side="left", padx=5)
        ttk.Button(self.backup_file_frame, text="Browse", command=self.browse_backup_file).pack(side="left")
        
        # For restore only - file to restore from (dropdown)
        self.restore_file_frame = ttk.Frame(self.file_options_frame)
        self.restore_file_var = tk.StringVar()
        self.restore_file_mapping = {}  # Initialize mapping of filename to full path
        ttk.Label(self.restore_file_frame, text="Restore from:").pack(side="left", padx=5)
        self.restore_file_combo = ttk.Combobox(self.restore_file_frame, textvariable=self.restore_file_var, width=50)
        self.restore_file_combo.pack(side="left", padx=5)
        ttk.Button(self.restore_file_frame, text="Browse", command=self.browse_restore_file).pack(side="left")
        ttk.Button(self.restore_file_frame, text="Refresh", command=self.refresh_restore_files).pack(side="left", padx=5)

        # Source connection
        self.source_frame = ttk.LabelFrame(
            main_container, text="Source Connection", padding="10"
        )
        self.source_frame.pack(fill="x", pady=5)

        ttk.Label(self.source_frame, text="Connection:").pack(side="left", padx=5)
        self.source_combo = ttk.Combobox(
            self.source_frame, textvariable=self.source_conn, width=30
        )
        self.source_combo.pack(side="left", padx=5)
        self.source_combo.bind(
            "<<ComboboxSelected>>", lambda e: self.on_source_selected()
        )

        ttk.Button(self.source_frame, text="Refresh", command=self.refresh_connections).pack(
            side="left", padx=5
        )
        ttk.Button(
            self.source_frame, text="Test", command=lambda: self.test_connection("source")
        ).pack(side="left", padx=5)

        # Source details
        self.source_details = ttk.Frame(self.source_frame)
        self.source_details.pack(side="left", padx=20)
        self.source_info_label = ttk.Label(
            self.source_details, text="No connection selected"
        )
        self.source_info_label.pack()

        # Destination connection
        self.dest_frame = ttk.LabelFrame(
            main_container, text="Destination Connection", padding="10"
        )
        self.dest_frame.pack(fill="x", pady=5)

        ttk.Label(self.dest_frame, text="Connection:").pack(side="left", padx=5)
        self.dest_combo = ttk.Combobox(
            self.dest_frame, textvariable=self.dest_conn, width=30
        )
        self.dest_combo.pack(side="left", padx=5)
        self.dest_combo.bind(
            "<<ComboboxSelected>>", lambda e: self.on_dest_selected()
        )

        ttk.Button(
            self.dest_frame, text="Test", command=lambda: self.test_connection("dest")
        ).pack(side="left", padx=5)

        # Destination details
        self.dest_details = ttk.Frame(self.dest_frame)
        self.dest_details.pack(side="left", padx=20)
        self.dest_info_label = ttk.Label(
            self.dest_details, text="No connection selected"
        )
        self.dest_info_label.pack()

        # Options
        options_frame = ttk.LabelFrame(main_container, text="Options", padding="10")
        options_frame.pack(fill="x", pady=5)

        self.db_only = tk.BooleanVar()
        self.filestore_only = tk.BooleanVar()
        self.verbose = tk.BooleanVar()

        ttk.Checkbutton(
            options_frame, text="Database Only", variable=self.db_only
        ).pack(side="left", padx=10)
        ttk.Checkbutton(
            options_frame, text="Filestore Only", variable=self.filestore_only
        ).pack(side="left", padx=10)
        ttk.Checkbutton(
            options_frame, text="Verbose Output", variable=self.verbose
        ).pack(side="left", padx=10)

        # Progress
        progress_frame = ttk.Frame(main_container)
        progress_frame.pack(fill="x", pady=10)

        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(anchor="w")

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill="x", pady=5)

        # Log - set fixed height instead of expanding
        log_frame = ttk.LabelFrame(main_container, text="Output Log", padding="5")
        log_frame.pack(fill="both", expand=False, pady=5)

        # Fixed height for log to ensure buttons are visible
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=True)

        # Configure tags for colored output
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("warning", foreground="orange")
        self.log_text.tag_config("success", foreground="green")
        self.log_text.tag_config("info", foreground="black")

        # Action buttons
        button_frame = ttk.Frame(main_container)
        button_frame.pack(pady=10)

        self.execute_btn = ttk.Button(
            button_frame,
            text="Execute Operation",
            command=self.execute_operation,
            style="Accent.TButton",
        )
        self.execute_btn.pack(side="left", padx=5)

        ttk.Button(button_frame, text="Clear Log", command=self.clear_log).pack(
            side="left", padx=5
        )
        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(
            side="left", padx=5
        )

        # Load connections
        self.refresh_connections()
        
        # Set initial UI state
        self.update_operation_ui()

    def create_connections_tab(self):
        """Create the connections management tab with separate sections"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Configuration")
        
        # Main container
        main_container = ttk.Frame(tab)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # === SETTINGS SECTION ===
        settings_frame = ttk.LabelFrame(main_container, text="Settings", padding="10")
        settings_frame.pack(fill="x", pady=(0, 10))
        
        # Backup Directory
        backup_dir_frame = ttk.Frame(settings_frame)
        backup_dir_frame.pack(fill="x", pady=5)
        
        ttk.Label(backup_dir_frame, text="Backup Directory:").pack(side="left", padx=(0, 10))
        
        self.backup_dir_var = tk.StringVar(value=self.backup_directory)
        backup_dir_entry = ttk.Entry(backup_dir_frame, textvariable=self.backup_dir_var, width=50)
        backup_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        def browse_backup_dir():
            directory = filedialog.askdirectory(title="Select Backup Directory", initialdir=self.backup_directory)
            if directory:
                self.backup_dir_var.set(directory)
                self.backup_directory = directory
                self.save_config()
                # Update the backup files tab
                self.refresh_backup_files()
                messagebox.showinfo("Success", f"Backup directory updated to: {directory}")
        
        ttk.Button(backup_dir_frame, text="Browse", command=browse_backup_dir).pack(side="left", padx=(0, 5))
        
        def apply_backup_dir():
            directory = self.backup_dir_var.get()
            if directory and os.path.exists(directory):
                self.backup_directory = directory
                self.save_config()
                self.refresh_backup_files()
                messagebox.showinfo("Success", "Backup directory updated successfully")
            else:
                messagebox.showerror("Error", "Invalid directory path")
        
        ttk.Button(backup_dir_frame, text="Apply", command=apply_backup_dir).pack(side="left")

        # Create PanedWindow for two sections
        paned = ttk.PanedWindow(main_container, orient="vertical")
        paned.pack(fill="both", expand=True)

        # === ODOO CONNECTIONS SECTION ===
        odoo_frame = ttk.LabelFrame(paned, text="Odoo Database Connections", padding="10")
        paned.add(odoo_frame, weight=1)

        # Treeview for Odoo connections
        odoo_list_frame = ttk.Frame(odoo_frame)
        odoo_list_frame.pack(fill="both", expand=True)
        
        columns = ("Host", "Port", "Database", "User", "Has SSH")
        self.odoo_tree = ttk.Treeview(
            odoo_list_frame, columns=columns, show="tree headings", height=8
        )
        self.odoo_tree.heading("#0", text="Connection Name")
        self.odoo_tree.heading("Host", text="DB Host")
        self.odoo_tree.heading("Port", text="Port")
        self.odoo_tree.heading("Database", text="Database")
        self.odoo_tree.heading("User", text="DB User")
        self.odoo_tree.heading("Has SSH", text="SSH")

        self.odoo_tree.column("#0", width=150)
        self.odoo_tree.column("Host", width=120)
        self.odoo_tree.column("Port", width=60)
        self.odoo_tree.column("Database", width=120)
        self.odoo_tree.column("User", width=100)
        self.odoo_tree.column("Has SSH", width=50)

        self.odoo_tree.pack(side="left", fill="both", expand=True)
        
        # Bind double-click event to edit Odoo connection
        self.odoo_tree.bind("<Double-Button-1>", lambda e: self.edit_odoo_connection())

        # Scrollbar for Odoo connections
        odoo_scrollbar = ttk.Scrollbar(
            odoo_list_frame, orient="vertical", command=self.odoo_tree.yview
        )
        odoo_scrollbar.pack(side="right", fill="y")
        self.odoo_tree.configure(yscrollcommand=odoo_scrollbar.set)

        # Buttons for Odoo connections
        odoo_btn_frame = ttk.Frame(odoo_frame)
        odoo_btn_frame.pack(pady=10)

        ttk.Button(
            odoo_btn_frame, text="Add Odoo Connection", command=self.add_odoo_connection_dialog
        ).pack(side="left", padx=5)
        ttk.Button(odoo_btn_frame, text="Edit", command=self.edit_odoo_connection).pack(
            side="left", padx=5
        )
        ttk.Button(odoo_btn_frame, text="Delete", command=self.delete_odoo_connection).pack(
            side="left", padx=5
        )
        ttk.Button(odoo_btn_frame, text="Test Connection", command=lambda: self.test_selected_connection("odoo")).pack(
            side="left", padx=5
        )

        # === SSH CONNECTIONS SECTION ===
        ssh_frame = ttk.LabelFrame(paned, text="SSH Server Connections", padding="10")
        paned.add(ssh_frame, weight=1)

        # Treeview for SSH connections
        ssh_list_frame = ttk.Frame(ssh_frame)
        ssh_list_frame.pack(fill="both", expand=True)
        
        ssh_columns = ("Host", "Port", "User", "Auth Type")
        self.ssh_tree = ttk.Treeview(
            ssh_list_frame, columns=ssh_columns, show="tree headings", height=8
        )
        self.ssh_tree.heading("#0", text="Connection Name")
        self.ssh_tree.heading("Host", text="SSH Host")
        self.ssh_tree.heading("Port", text="Port")
        self.ssh_tree.heading("User", text="SSH User")
        self.ssh_tree.heading("Auth Type", text="Auth")

        self.ssh_tree.column("#0", width=150)
        self.ssh_tree.column("Host", width=150)
        self.ssh_tree.column("Port", width=60)
        self.ssh_tree.column("User", width=120)
        self.ssh_tree.column("Auth Type", width=100)

        self.ssh_tree.pack(side="left", fill="both", expand=True)
        
        # Bind double-click event to edit SSH connection
        self.ssh_tree.bind("<Double-Button-1>", lambda e: self.edit_ssh_connection())

        # Scrollbar for SSH connections
        ssh_scrollbar = ttk.Scrollbar(
            ssh_list_frame, orient="vertical", command=self.ssh_tree.yview
        )
        ssh_scrollbar.pack(side="right", fill="y")
        self.ssh_tree.configure(yscrollcommand=ssh_scrollbar.set)

        # Buttons for SSH connections
        ssh_btn_frame = ttk.Frame(ssh_frame)
        ssh_btn_frame.pack(pady=10)

        ttk.Button(
            ssh_btn_frame, text="Add SSH Connection", command=self.add_ssh_connection_dialog
        ).pack(side="left", padx=5)
        ttk.Button(ssh_btn_frame, text="Edit", command=self.edit_ssh_connection).pack(
            side="left", padx=5
        )
        ttk.Button(ssh_btn_frame, text="Delete", command=self.delete_ssh_connection).pack(
            side="left", padx=5
        )
        ttk.Button(ssh_btn_frame, text="Test SSH", command=lambda: self.test_selected_connection("ssh")).pack(
            side="left", padx=5
        )

        # Load connections
        self.load_connections_list()

    def create_backup_files_tab(self):
        """Create the backup files management tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Backup Files")
        
        # Main container
        main_frame = ttk.Frame(tab, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Header with current directory info
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(header_frame, text="Current Directory:").pack(side="left", padx=(0, 5))
        self.current_dir_label = ttk.Label(header_frame, text=os.getcwd(), font=("TkDefaultFont", 9, "bold"))
        self.current_dir_label.pack(side="left")
        
        # Files list frame
        list_frame = ttk.LabelFrame(main_frame, text="Backup Files", padding="10")
        list_frame.pack(fill="both", expand=True)
        
        # Treeview for files
        columns = ("Size", "Date Modified", "Type")
        self.files_tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", height=15)
        self.files_tree.heading("#0", text="Filename")
        self.files_tree.heading("Size", text="Size")
        self.files_tree.heading("Date Modified", text="Modified")
        self.files_tree.heading("Type", text="Type")
        
        self.files_tree.column("#0", width=350)
        self.files_tree.column("Size", width=100)
        self.files_tree.column("Date Modified", width=150)
        self.files_tree.column("Type", width=100)
        
        # Scrollbars
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.files_tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.files_tree.xview)
        self.files_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Grid layout for treeview and scrollbars
        self.files_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # Bind double-click to view file details
        self.files_tree.bind("<Double-Button-1>", self.view_backup_file_details)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(button_frame, text="Refresh", command=self.refresh_backup_files).pack(side="left", padx=5)
        ttk.Button(button_frame, text="View Details", command=self.view_selected_backup_details).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Delete", command=self.delete_selected_backup).pack(side="left", padx=5)
        
        # Stats frame
        stats_frame = ttk.Frame(main_frame)
        stats_frame.pack(fill="x", pady=(10, 0))
        
        self.backup_stats_label = ttk.Label(stats_frame, text="", font=("TkDefaultFont", 9))
        self.backup_stats_label.pack(side="left")
        
        # Initial load
        self.refresh_backup_files()

    def refresh_backup_files(self):
        """Refresh the list of backup files in the backup directory"""
        # Clear existing items
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)
        
        # Use configured backup directory
        current_dir = self.backup_directory
        self.current_dir_label.config(text=current_dir)
        
        # Look for backup files (tar.gz files)
        backup_files = []
        total_size = 0
        
        try:
            for file in os.listdir(current_dir):
                if file.endswith('.tar.gz') or file.endswith('.tgz') or file.endswith('.zip'):
                    file_path = os.path.join(current_dir, file)
                    if os.path.isfile(file_path):
                        stat = os.stat(file_path)
                        size = stat.st_size
                        total_size += size
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                        
                        # Determine type based on filename pattern
                        file_type = "Unknown"
                        if "_backup_" in file or "_restore_" in file:
                            file_type = "Odoo Backup"
                        elif "filestore" in file.lower():
                            file_type = "Filestore"
                        elif "database" in file.lower() or "db" in file.lower():
                            file_type = "Database"
                        
                        backup_files.append({
                            'name': file,
                            'path': file_path,
                            'size': size,
                            'mtime': mtime,
                            'type': file_type
                        })
            
            # Sort by modification time (newest first)
            backup_files.sort(key=lambda x: x['mtime'], reverse=True)
            
            # Add to tree
            for backup in backup_files:
                size_str = self.format_file_size(backup['size'])
                date_str = backup['mtime'].strftime("%Y-%m-%d %H:%M:%S")
                
                self.files_tree.insert('', 'end', text=backup['name'],
                                      values=(size_str, date_str, backup['type']),
                                      tags=(backup['path'],))
            
            # Update stats
            total_size_str = self.format_file_size(total_size)
            self.backup_stats_label.config(text=f"Total: {len(backup_files)} backup files, {total_size_str}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list backup files: {str(e)}")
    
    def format_file_size(self, size):
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"
    
    def view_backup_file_details(self, event=None):
        """View details of a backup file"""
        self.view_selected_backup_details()
    
    def view_selected_backup_details(self):
        """View details of the selected backup file"""
        selection = self.files_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup file to view details.")
            return
        
        item = self.files_tree.item(selection[0])
        filename = item['text']
        file_path = item['tags'][0] if item['tags'] else None
        
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "File not found.")
            return
        
        try:
            # Open file with the system's default application
            import platform
            import subprocess
            
            if platform.system() == 'Darwin':       # macOS
                subprocess.call(('open', file_path))
            elif platform.system() == 'Windows':    # Windows
                os.startfile(file_path)
            else:                                   # Linux and others
                subprocess.call(('xdg-open', file_path))
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open backup file: {str(e)}")
    
    def delete_selected_backup(self):
        """Delete the selected backup file"""
        selection = self.files_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup file to delete.")
            return
        
        item = self.files_tree.item(selection[0])
        filename = item['text']
        file_path = item['tags'][0] if item['tags'] else None
        
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "File not found.")
            return
        
        # Confirm deletion
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{filename}'?\n\nThis action cannot be undone."):
            try:
                os.remove(file_path)
                messagebox.showinfo("Success", f"File '{filename}' has been deleted.")
                self.refresh_backup_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete file: {str(e)}")
    
    def add_odoo_connection_dialog(self):
        """Show dialog to add a new Odoo database connection"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Odoo Database Connection")
        
        # Make dialog modal
        dialog.transient(self.root)
        dialog.resizable(False, False)
        
        # Main container with padding
        main_frame = ttk.Frame(dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Connection fields dictionary
        fields = {}
        
        # Load button at top
        ttk.Button(
            main_frame,
            text="Load from odoo.conf",
            command=lambda: self.load_from_odoo_conf(fields),
        ).pack(pady=(0, 15))
        
        # Connection Details Frame
        details_frame = ttk.LabelFrame(main_frame, text="Connection Details", padding="10")
        details_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Form fields
        row = 0
        for label, field_name, default, width in [
            ("Connection Name:", "name", "", 30),
            ("Host:", "host", "localhost", 30),
            ("Port:", "port", "5432", 30),
            ("Database:", "database", "", 30),
            ("Username:", "username", "odoo", 30),
            ("Password:", "password", "", 30),
        ]:
            ttk.Label(details_frame, text=label).grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
            entry = ttk.Entry(details_frame, width=width)
            if field_name == "password":
                entry.config(show="*")
            entry.insert(0, default)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            fields[field_name] = entry
            row += 1
        
        # Filestore Path with Browse button
        ttk.Label(details_frame, text="Filestore Path:").grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
        path_frame = ttk.Frame(details_frame)
        path_frame.grid(row=row, column=1, sticky="ew", pady=5)
        fields["filestore_path"] = ttk.Entry(path_frame, width=22)
        # Set default filestore path for Odoo 17
        import os
        default_filestore = os.path.expanduser("~/.local/share/Odoo")
        fields["filestore_path"].insert(0, default_filestore)
        fields["filestore_path"].pack(side=tk.LEFT, fill=tk.X, expand=True)
        fields["browse_button"] = ttk.Button(
            path_frame,
            text="Browse",
            command=lambda: self.browse_folder_entry(fields["filestore_path"]),
            width=8
        )
        fields["browse_button"].pack(side=tk.LEFT, padx=(5, 0))
        row += 1
        
        # Odoo Version
        ttk.Label(details_frame, text="Odoo Version:").grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
        fields["odoo_version"] = ttk.Combobox(
            details_frame, width=28, values=["18.0", "17.0", "16.0", "15.0", "14.0", "13.0", "12.0"]
        )
        fields["odoo_version"].grid(row=row, column=1, sticky="ew", pady=5)
        fields["odoo_version"].set("17.0")
        row += 1
        
        # Local Development checkbox
        fields["is_local"] = tk.BooleanVar()
        ttk.Checkbutton(
            details_frame, text="Local Development Connection", variable=fields["is_local"]
        ).grid(row=row, column=1, sticky="w", pady=5)
        
        # Configure column to expand
        details_frame.columnconfigure(1, weight=1)
        
        # SSH Options Frame
        ssh_frame = ttk.LabelFrame(main_frame, text="Remote Server Access", padding="10")
        ssh_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Define toggle function first
        def toggle_ssh_dropdown():
            """Enable/disable SSH connection dropdown and browse button based on checkbox"""
            if fields["use_ssh"].get():
                # SSH enabled - enable dropdown, disable browse button
                fields["ssh_connection"].config(state="readonly")
                fields["browse_button"].config(state="disabled")
            else:
                # SSH disabled - disable dropdown, enable browse button
                fields["ssh_connection"].config(state="disabled")
                fields["browse_button"].config(state="normal")
        
        fields["use_ssh"] = tk.BooleanVar()
        ssh_check = ttk.Checkbutton(
            ssh_frame, 
            text="Use SSH connection for remote server access", 
            variable=fields["use_ssh"],
            command=toggle_ssh_dropdown
        )
        ssh_check.pack(anchor="w", pady=(0, 5))
        
        # SSH Connection Dropdown
        ssh_select_frame = ttk.Frame(ssh_frame)
        ssh_select_frame.pack(fill=tk.X)
        
        ttk.Label(ssh_select_frame, text="SSH Connection:").pack(side=tk.LEFT, padx=(20, 10))
        
        # Get list of SSH connections
        ssh_connections = []
        ssh_connection_map = {}  # Map names to IDs
        all_connections = self.conn_manager.list_connections()
        for conn in all_connections:
            if conn['type'] == "ssh":
                ssh_connections.append(conn['name'])
                ssh_connection_map[conn['name']] = conn['id']
        
        fields["ssh_connection"] = ttk.Combobox(
            ssh_select_frame, width=30, values=ssh_connections, state="disabled"
        )
        fields["ssh_connection"].pack(side=tk.LEFT, fill=tk.X, expand=True)
        if ssh_connections:
            fields["ssh_connection"].set(ssh_connections[0])
        
        # Button frame at bottom
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        def save_connection():
            config = {
                "connection_type": "odoo",
                "host": fields["host"].get(),
                "port": int(fields["port"].get() or 5432),
                "database": fields["database"].get(),
                "username": fields["username"].get(),
                "password": fields["password"].get(),
                "filestore_path": fields["filestore_path"].get(),
                "odoo_version": fields["odoo_version"].get(),
                "is_local": fields["is_local"].get(),
                "use_ssh": fields["use_ssh"].get(),
            }
            
            # If SSH is enabled, find the SSH connection ID
            if fields["use_ssh"].get() and fields["ssh_connection"].get():
                selected_ssh_name = fields["ssh_connection"].get()
                if selected_ssh_name in ssh_connection_map:
                    config["ssh_connection_id"] = ssh_connection_map[selected_ssh_name]
                    config["ssh_connection_name"] = selected_ssh_name
            else:
                config["ssh_connection_id"] = None
                config["ssh_connection_name"] = ""

            name = fields["name"].get()
            if not name:
                messagebox.showerror("Error", "Connection name is required")
                return

            if self.conn_manager.save_connection(name, config):
                dialog.destroy()
                self.load_connections_list()
                self.refresh_connections()
            else:
                messagebox.showerror("Error", "Failed to save connection")
        
        # Center the buttons
        ttk.Button(button_frame, text="Test Connection", 
                  command=lambda: self.test_connection_config(fields)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save", command=save_connection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        # Center dialog on parent after it's built
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Make it modal after geometry is set
        dialog.grab_set()

    def load_from_odoo_conf(self, fields):
        """Load connection settings from odoo.conf file - local or remote based on SSH checkbox"""
        # Check if SSH is enabled
        if fields.get("use_ssh") and fields["use_ssh"].get():
            # Load from remote via SSH
            self.load_from_remote_odoo_conf(fields)
        else:
            # Load from local file
            conf_file = filedialog.askopenfilename(
                title="Select odoo.conf file",
                filetypes=[("Config files", "*.conf"), ("All files", "*.*")]
            )
            
            if not conf_file:
                return
            
            try:
                # Parse the config file
                config = OdooBackupRestore.parse_odoo_conf(conf_file)
                
                # Update the form fields
                fields["host"].delete(0, tk.END)
                fields["host"].insert(0, config["host"])
                
                fields["port"].delete(0, tk.END)
                fields["port"].insert(0, config["port"])
                
                if config["database"]:
                    fields["database"].delete(0, tk.END)
                    fields["database"].insert(0, config["database"])
                
                fields["username"].delete(0, tk.END)
                fields["username"].insert(0, config["username"])
                
                if config["password"]:
                    fields["password"].delete(0, tk.END)
                    fields["password"].insert(0, config["password"])
                
                if config["filestore_path"]:
                    fields["filestore_path"].delete(0, tk.END)
                    fields["filestore_path"].insert(0, config["filestore_path"])
                
                fields["odoo_version"].set(config["odoo_version"])
                fields["is_local"].set(config["is_local"])
                
                # Suggest a connection name based on the config file
                if not fields["name"].get():
                    config_name = os.path.basename(conf_file).replace('.conf', '')
                    fields["name"].delete(0, tk.END)
                    fields["name"].insert(0, config_name)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load config: {str(e)}")
    
    def load_from_remote_odoo_conf(self, fields):
        """Load connection settings from a remote odoo.conf file via SSH"""
        # First, select an SSH connection
        ssh_dialog = tk.Toplevel(self.root)
        ssh_dialog.title("Load Remote odoo.conf")
        ssh_dialog.geometry("400x150")
        
        # Center dialog
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 75
        ssh_dialog.geometry(f"400x150+{x}+{y}")
        
        ssh_dialog.transient(self.root)
        ssh_dialog.grab_set()
        
        ssh_fields = {}
        
        # Get list of SSH connections
        ssh_connections = []
        all_connections = self.conn_manager.list_connections()
        for conn in all_connections:
            if conn['type'] == "ssh":
                ssh_connections.append(conn['name'])
        
        if not ssh_connections:
            messagebox.showerror("Error", "No SSH connections found. Please add an SSH connection first.")
            ssh_dialog.destroy()
            return
        
        row = 0
        ttk.Label(ssh_dialog, text="SSH Connection:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        ssh_fields["connection"] = ttk.Combobox(ssh_dialog, width=25, values=ssh_connections, state="readonly")
        ssh_fields["connection"].grid(row=row, column=1, padx=5, pady=5)
        ssh_fields["connection"].set(ssh_connections[0])
        
        row += 1
        ttk.Label(ssh_dialog, text="Config Path:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        ssh_fields["config_path"] = ttk.Entry(ssh_dialog, width=25)
        ssh_fields["config_path"].grid(row=row, column=1, padx=5, pady=5)
        ssh_fields["config_path"].insert(0, "/home/administrator/qlf/odoo/odoo.conf")
        
        def connect_and_load():
            try:
                # Get selected SSH connection
                selected_ssh_name = ssh_fields["connection"].get()
                # Find the SSH connection by name
                connections = self.conn_manager.list_connections()
                ssh_conn_id = None
                for conn in connections:
                    if conn['type'] == 'ssh' and conn['name'] == selected_ssh_name:
                        ssh_conn_id = conn['id']
                        break
                
                if not ssh_conn_id:
                    messagebox.showerror("Error", f"SSH connection '{selected_ssh_name}' not found")
                    return
                
                ssh_conn = self.conn_manager.get_ssh_connection(ssh_conn_id)
                if not ssh_conn:
                    messagebox.showerror("Error", f"SSH connection '{selected_ssh_name}' not found")
                    return
                
                # Create SSH client
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Connect using selected connection
                connect_params = {
                    "hostname": ssh_conn.get("host"),
                    "port": ssh_conn.get("port", 22),
                    "username": ssh_conn.get("username"),
                    "timeout": 10,
                    "banner_timeout": 10,
                    "auth_timeout": 10
                }
                
                if ssh_conn.get("ssh_key_path"):
                    connect_params["key_filename"] = ssh_conn.get("ssh_key_path")
                elif ssh_conn.get("password"):
                    connect_params["password"] = ssh_conn.get("password")
                
                ssh.connect(**connect_params)
                
                # Read the config file
                sftp = ssh.open_sftp()
                config_path = ssh_fields["config_path"].get()
                
                with sftp.open(config_path, 'r') as remote_file:
                    config_content = remote_file.read().decode('utf-8')
                
                sftp.close()
                ssh.close()
                
                # Parse the config
                config_parser = configparser.ConfigParser()
                config_parser.read_string(config_content)
                
                if 'options' not in config_parser:
                    raise ValueError("No 'options' section found in config file")
                
                options = config_parser['options']
                
                # Update form fields
                fields["host"].delete(0, tk.END)
                fields["host"].insert(0, options.get('db_host', 'localhost'))
                
                fields["port"].delete(0, tk.END)
                fields["port"].insert(0, options.get('db_port', '5432'))
                
                if options.get('db_name') and options.get('db_name') != 'False':
                    fields["database"].delete(0, tk.END)
                    fields["database"].insert(0, options.get('db_name'))
                
                fields["username"].delete(0, tk.END)
                fields["username"].insert(0, options.get('db_user', 'odoo'))
                
                if options.get('db_password') and options.get('db_password') != 'False':
                    fields["password"].delete(0, tk.END)
                    fields["password"].insert(0, options.get('db_password'))
                
                # Set SSH connection
                fields["use_ssh"].set(True)
                # Enable SSH dropdown
                if "ssh_connection" in fields:
                    fields["ssh_connection"].config(state="readonly")
                    fields["ssh_connection"].set(selected_ssh_name)
                
                # Try to determine remote filestore path
                data_dir = options.get('data_dir')
                db_name = options.get('db_name', '')
                
                if data_dir and data_dir != 'False':
                    if db_name and db_name != 'False':
                        filestore_path = f"{data_dir}/filestore/{db_name}"
                    else:
                        filestore_path = f"{data_dir}/filestore"
                else:
                    # No data_dir in config, use default based on Odoo version
                    odoo_version = fields["odoo_version"].get()
                    if db_name and db_name != 'False':
                        filestore_path = f"/var/lib/odoo/.local/share/Odoo/filestore/{db_name}"
                    else:
                        filestore_path = "/var/lib/odoo/.local/share/Odoo/filestore"
                
                fields["filestore_path"].delete(0, tk.END)
                fields["filestore_path"].insert(0, filestore_path)
                
                ssh_dialog.destroy()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load remote config: {str(e)}")
        
        btn_frame = ttk.Frame(ssh_dialog)
        btn_frame.grid(row=row + 1, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="Connect & Load", command=connect_and_load).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=ssh_dialog.destroy).pack(side="left", padx=5)
    
    def test_connection_config(self, fields):
        """Test connection from config fields"""
        # First test SSH connection if enabled
        if fields.get("use_ssh") and fields["use_ssh"].get():
            # Get selected SSH connection from dropdown
            selected_ssh = fields.get("ssh_connection")
            if not selected_ssh or not selected_ssh.get():
                messagebox.showerror("Error", "Please select an SSH connection")
                return
            
            # Find SSH connection by name
            selected_ssh_name = selected_ssh.get()
            connections = self.conn_manager.list_connections()
            ssh_conn_id = None
            for conn in connections:
                if conn['type'] == 'ssh' and conn['name'] == selected_ssh_name:
                    ssh_conn_id = conn['id']
                    break
            
            if not ssh_conn_id:
                messagebox.showerror("Error", f"SSH connection '{selected_ssh_name}' not found")
                return
                
            ssh_conn = self.conn_manager.get_ssh_connection(ssh_conn_id)
            if not ssh_conn:
                messagebox.showerror("Error", f"SSH connection '{selected_ssh_name}' not found")
                return
            
            try:
                # Test SSH connection
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Connect with password or key
                connect_kwargs = {
                    "hostname": ssh_conn.get("host"),
                    "port": ssh_conn.get("port", 22),
                    "username": ssh_conn.get("username"),
                    "timeout": 10,
                    "banner_timeout": 10,
                    "auth_timeout": 10
                }
                
                if ssh_conn.get("ssh_key_path") and os.path.exists(ssh_conn.get("ssh_key_path")):
                    connect_kwargs["key_filename"] = ssh_conn.get("ssh_key_path")
                elif ssh_conn.get("password"):
                    connect_kwargs["password"] = ssh_conn.get("password")
                else:
                    messagebox.showerror("Error", "SSH password or key file is required")
                    return
                
                ssh.connect(**connect_kwargs)
                
                # Test if we can execute a simple command
                stdin, stdout, stderr = ssh.exec_command("echo 'SSH connection successful'")
                stdout.read()
                
                ssh.close()
                
                # Now test database connection through SSH tunnel
                messagebox.showinfo("Success", "SSH connection successful! Testing database connection...")
                
            except Exception as e:
                messagebox.showerror("Error", f"SSH connection failed: {str(e)}")
                return
        
        # Test database connection
        # Find SSH connection ID if SSH is enabled
        ssh_conn_id = None
        if fields.get("use_ssh") and fields["use_ssh"].get() and fields.get("ssh_connection"):
            selected_ssh_name = fields["ssh_connection"].get()
            if selected_ssh_name:
                connections = self.conn_manager.list_connections()
                for conn in connections:
                    if conn['type'] == 'ssh' and conn['name'] == selected_ssh_name:
                        ssh_conn_id = conn['id']
                        break
        
        config = {
            "db_host": fields["host"].get(),
            "db_port": int(fields["port"].get() or 5432),
            "db_user": fields["username"].get(),
            "db_password": fields["password"].get(),
            "db_name": fields["database"].get(),
            "filestore_path": fields["filestore_path"].get() if fields.get("filestore_path") else None,
            "use_ssh": fields.get("use_ssh", {}).get() if fields.get("use_ssh") else False,
            "ssh_connection_id": ssh_conn_id
        }

        tool = OdooBackupRestore(conn_manager=self.conn_manager)
        success, msg = tool.test_connection(config)

        messagebox.showinfo("Test Results", msg)

    def browse_folder_entry(self, entry):
        """Browse for folder and set entry value"""
        folder = filedialog.askdirectory()
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
    
    def browse_file_entry(self, entry):
        """Browse for file and set entry value"""
        file_path = filedialog.askopenfilename(
            title="Select SSH Key File",
            filetypes=[("All files", "*.*"), ("PEM files", "*.pem"), ("Key files", "*.key")]
        )
        if file_path:
            entry.delete(0, tk.END)
            entry.insert(0, file_path)

    def load_connections_list(self):
        """Load connections into both treeviews using IDs"""
        connections = self.conn_manager.list_connections()
        
        # Load Odoo connections if tree exists
        if hasattr(self, 'odoo_tree'):
            # Clear existing items
            for item in self.odoo_tree.get_children():
                self.odoo_tree.delete(item)
            
            # Load Odoo connections
            for conn in connections:
                if conn['type'] == 'odoo':
                    # Get full details using ID
                    conn_details = self.conn_manager.get_odoo_connection(conn['id'])
                    if conn_details:
                        has_ssh = "Yes" if conn_details.get("use_ssh") else "No"
                        # Store the ID in the tree item
                        item_id = self.odoo_tree.insert(
                            "", "end", text=conn['name'],
                            values=(
                                conn_details.get("host", ""),
                                conn_details.get("port", "5432"),
                                conn_details.get("database", ""),
                                conn_details.get("username", ""),
                                has_ssh
                            ),
                            tags=(str(conn['id']),)  # Store ID in tags
                        )
        
        # Load SSH connections if tree exists
        if hasattr(self, 'ssh_tree'):
            # Clear existing items
            for item in self.ssh_tree.get_children():
                self.ssh_tree.delete(item)
            
            # Load SSH connections
            for conn in connections:
                if conn['type'] == 'ssh':
                    # Get full details using ID
                    conn_details = self.conn_manager.get_ssh_connection(conn['id'])
                    if conn_details:
                        auth_type = "Key" if conn_details.get("ssh_key_path") else "Password"
                        item_id = self.ssh_tree.insert(
                            "", "end", text=conn['name'],
                            values=(
                                conn_details.get("host", ""),
                                conn_details.get("port", "22"),
                                conn_details.get("username", ""),
                                auth_type
                            ),
                            tags=(str(conn['id']),)  # Store ID in tags
                        )

    def add_ssh_connection_dialog(self):
        """Show dialog to add a new SSH connection"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add SSH Connection")
        dialog.geometry("400x350")
        
        # Center dialog
        self.root.update_idletasks()
        width = 400
        height = 350
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (width // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        dialog.transient(self.root)
        dialog.grab_set()
        
        fields = {}
        row = 0
        
        ttk.Label(dialog, text="Connection Name:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["name"] = ttk.Entry(dialog, width=25)
        fields["name"].grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(dialog, text="SSH Host:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["host"] = ttk.Entry(dialog, width=25)
        fields["host"].grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(dialog, text="SSH Port:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["port"] = ttk.Entry(dialog, width=25)
        fields["port"].grid(row=row, column=1, padx=5, pady=5)
        fields["port"].insert(0, "22")
        
        row += 1
        ttk.Label(dialog, text="SSH User:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["user"] = ttk.Entry(dialog, width=25)
        fields["user"].grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(dialog, text="Authentication:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        auth_frame = ttk.Frame(dialog)
        auth_frame.grid(row=row, column=1, padx=5, pady=5)
        
        auth_var = tk.StringVar(value="password")
        ttk.Radiobutton(auth_frame, text="Password", variable=auth_var, value="password").pack(side="left")
        ttk.Radiobutton(auth_frame, text="Key File", variable=auth_var, value="key").pack(side="left")
        fields["auth_type"] = auth_var
        
        row += 1
        ttk.Label(dialog, text="Password:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["password"] = ttk.Entry(dialog, width=25, show="*")
        fields["password"].grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(dialog, text="Key File:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        key_frame = ttk.Frame(dialog)
        key_frame.grid(row=row, column=1, padx=5, pady=5)
        fields["key_path"] = ttk.Entry(key_frame, width=18)
        fields["key_path"].pack(side="left")
        ttk.Button(key_frame, text="Browse", command=lambda: self.browse_file_entry(fields["key_path"])).pack(side="left", padx=2)
        
        def save_ssh_connection():
            # Save as SSH-type connection
            config = {
                "connection_type": "ssh",
                "host": fields["host"].get(),
                "port": int(fields["port"].get() or 22),
                "database": "",  # SSH connections don't have database
                "username": fields["user"].get(),
                "password": fields["password"].get() if fields["auth_type"].get() == "password" else "",
                "ssh_key_path": fields["key_path"].get() if fields["auth_type"].get() == "key" else "",
            }
            
            name = fields["name"].get()
            if not name:
                messagebox.showerror("Error", "Connection name is required")
                return
            
            if self.conn_manager.save_connection(name, config):
                dialog.destroy()
                self.load_connections_list()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=row + 1, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="Test SSH", command=lambda: self.test_ssh_from_dialog(fields)).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save", command=save_ssh_connection).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)
    
    def edit_odoo_connection(self):
        """Edit selected Odoo connection"""
        selection = self.odoo_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an Odoo connection to edit")
            return
        
        # Get connection ID from tree item
        item = self.odoo_tree.item(selection[0])
        conn_id = int(item["tags"][0]) if item["tags"] else None
        
        if not conn_id:
            messagebox.showerror("Error", "Could not get connection ID")
            return
        
        # Get connection details using ID
        conn = self.conn_manager.get_odoo_connection(conn_id)
        if not conn:
            return
        
        original_name = conn["name"]
        original_id = conn_id
        
        # Show edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Connection: {original_name}")
        
        # Make dialog modal
        dialog.transient(self.root)
        dialog.resizable(False, False)
        
        # Main container with padding
        main_frame = ttk.Frame(dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Connection fields dictionary
        fields = {}
        
        # Load button at top
        ttk.Button(
            main_frame,
            text="Load from odoo.conf",
            command=lambda: self.load_from_odoo_conf(fields),
        ).pack(pady=(0, 15))
        
        # Connection Details Frame
        details_frame = ttk.LabelFrame(main_frame, text="Connection Details", padding="10")
        details_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Form fields
        row = 0
        for label, field_name, default_key, width in [
            ("Connection Name:", "name", "name", 30),
            ("Host:", "host", "host", 30),
            ("Port:", "port", "port", 30),
            ("Database:", "database", "database", 30),
            ("Username:", "username", "username", 30),
            ("Password:", "password", "password", 30),
        ]:
            ttk.Label(details_frame, text=label).grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
            entry = ttk.Entry(details_frame, width=width)
            if field_name == "password":
                entry.config(show="*")
            # Get value from conn dict, with default
            value = conn.get(default_key, "")
            if field_name == "port":
                value = str(value) if value else "5432"
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            fields[field_name] = entry
            row += 1
        
        # Filestore Path with Browse button
        ttk.Label(details_frame, text="Filestore Path:").grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
        path_frame = ttk.Frame(details_frame)
        path_frame.grid(row=row, column=1, sticky="ew", pady=5)
        fields["filestore_path"] = ttk.Entry(path_frame, width=22)
        fields["filestore_path"].insert(0, conn.get("filestore_path", ""))
        fields["filestore_path"].pack(side=tk.LEFT, fill=tk.X, expand=True)
        fields["browse_button"] = ttk.Button(
            path_frame,
            text="Browse",
            command=lambda: self.browse_folder_entry(fields["filestore_path"]),
            width=8
        )
        fields["browse_button"].pack(side=tk.LEFT, padx=(5, 0))
        row += 1
        
        # Odoo Version
        ttk.Label(details_frame, text="Odoo Version:").grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
        fields["odoo_version"] = ttk.Combobox(
            details_frame, width=28, values=["18.0", "17.0", "16.0", "15.0", "14.0", "13.0", "12.0"]
        )
        fields["odoo_version"].grid(row=row, column=1, sticky="ew", pady=5)
        fields["odoo_version"].set(conn.get("odoo_version", "17.0"))
        row += 1
        
        # Local Development checkbox
        fields["is_local"] = tk.BooleanVar(value=conn.get("is_local", False))
        ttk.Checkbutton(
            details_frame, text="Local Development Connection", variable=fields["is_local"]
        ).grid(row=row, column=1, sticky="w", pady=5)
        
        # Configure column to expand
        details_frame.columnconfigure(1, weight=1)
        
        # SSH Options Frame
        ssh_frame = ttk.LabelFrame(main_frame, text="Remote Server Access", padding="10")
        ssh_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        fields["use_ssh"] = tk.BooleanVar(value=conn.get("ssh_connection_id") is not None)
        ssh_check = ttk.Checkbutton(
            ssh_frame, 
            text="Use SSH connection for remote server access", 
            variable=fields["use_ssh"],
            command=lambda: toggle_ssh_dropdown()
        )
        ssh_check.pack(anchor="w", pady=(0, 5))
        
        # SSH Connection Dropdown
        ssh_select_frame = ttk.Frame(ssh_frame)
        ssh_select_frame.pack(fill=tk.X)
        
        ttk.Label(ssh_select_frame, text="SSH Connection:").pack(side=tk.LEFT, padx=(20, 10))
        
        # Get list of SSH connections
        ssh_connections = []
        ssh_connection_map = {}  # Map names to IDs
        all_connections = self.conn_manager.list_connections()
        for conn_data in all_connections:
            if conn_data['type'] == "ssh":
                ssh_connections.append(conn_data['name'])
                ssh_connection_map[conn_data['name']] = conn_data['id']
        
        fields["ssh_connection"] = ttk.Combobox(
            ssh_select_frame, width=30, values=ssh_connections, state="disabled"
        )
        fields["ssh_connection"].pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Set current SSH connection if it exists
        if conn.get("ssh_connection_id"):
            # Find the name of the SSH connection by ID
            for name, ssh_id in ssh_connection_map.items():
                if ssh_id == conn.get("ssh_connection_id"):
                    fields["ssh_connection"].set(name)
                    fields["ssh_connection"].config(state="readonly")
                    break
        elif ssh_connections:
            fields["ssh_connection"].set(ssh_connections[0])
        
        def toggle_ssh_dropdown():
            """Enable/disable SSH connection dropdown and browse button based on checkbox"""
            if fields["use_ssh"].get():
                # SSH enabled - enable dropdown, disable browse button
                fields["ssh_connection"].config(state="readonly")
                fields["browse_button"].config(state="disabled")
            else:
                # SSH disabled - disable dropdown, enable browse button
                fields["ssh_connection"].config(state="disabled")
                fields["browse_button"].config(state="normal")
        
        # Set initial state based on whether SSH is being used
        toggle_ssh_dropdown()
        
        # Button frame at bottom
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        def save_connection():
            config = {
                "connection_type": "odoo",
                "host": fields["host"].get(),
                "port": int(fields["port"].get() or 5432),
                "database": fields["database"].get(),
                "username": fields["username"].get(),
                "password": fields["password"].get(),
                "filestore_path": fields["filestore_path"].get(),
                "odoo_version": fields["odoo_version"].get(),
                "is_local": fields["is_local"].get(),
                "use_ssh": fields["use_ssh"].get(),
            }
            
            # If SSH is enabled, find the SSH connection ID
            if fields["use_ssh"].get() and fields["ssh_connection"].get():
                selected_ssh_name = fields["ssh_connection"].get()
                if selected_ssh_name in ssh_connection_map:
                    config["ssh_connection_id"] = ssh_connection_map[selected_ssh_name]
            else:
                config["ssh_connection_id"] = None
            
            new_name = fields["name"].get()
            if not new_name:
                messagebox.showerror("Error", "Connection name is required")
                return
            
            # Update the connection using ID
            if self.conn_manager.update_odoo_connection(original_id, new_name, config):
                dialog.destroy()
                self.load_connections_list()
                self.refresh_connections()
            else:
                messagebox.showerror("Error", "Failed to update connection")
        
        # Center the buttons
        ttk.Button(button_frame, text="Test Connection", 
                  command=lambda: self.test_connection_config(fields)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save", command=save_connection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        # Center dialog on parent after it's built
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Make it modal after geometry is set
        dialog.grab_set()
    
    def edit_ssh_connection(self):
        """Edit selected SSH connection"""
        selection = self.ssh_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an SSH connection to edit")
            return
        
        # Get connection ID from tree item
        item = self.ssh_tree.item(selection[0])
        conn_id = int(item["tags"][0]) if item["tags"] else None
        
        if not conn_id:
            messagebox.showerror("Error", "Could not get connection ID")
            return
        
        # Get connection details using ID
        conn = self.conn_manager.get_ssh_connection(conn_id)
        if not conn:
            return
        
        original_name = conn["name"]
        original_id = conn_id
        
        # Show edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit SSH Connection: {original_name}")
        dialog.geometry("400x350")
        
        # Center dialog
        self.root.update_idletasks()
        width = 400
        height = 350
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (width // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        dialog.transient(self.root)
        dialog.grab_set()
        
        fields = {}
        row = 0
        
        ttk.Label(dialog, text="Connection Name:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["name"] = ttk.Entry(dialog, width=25)
        fields["name"].grid(row=row, column=1, padx=5, pady=5)
        fields["name"].insert(0, original_name)
        
        row += 1
        ttk.Label(dialog, text="SSH Host:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["host"] = ttk.Entry(dialog, width=25)
        fields["host"].grid(row=row, column=1, padx=5, pady=5)
        fields["host"].insert(0, conn.get("host", ""))
        
        row += 1
        ttk.Label(dialog, text="SSH Port:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["port"] = ttk.Entry(dialog, width=25)
        fields["port"].grid(row=row, column=1, padx=5, pady=5)
        fields["port"].insert(0, str(conn.get("port", 22)))
        
        row += 1
        ttk.Label(dialog, text="SSH User:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["user"] = ttk.Entry(dialog, width=25)
        fields["user"].grid(row=row, column=1, padx=5, pady=5)
        fields["user"].insert(0, conn.get("username", ""))
        
        row += 1
        ttk.Label(dialog, text="Authentication:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        auth_frame = ttk.Frame(dialog)
        auth_frame.grid(row=row, column=1, padx=5, pady=5)
        
        # Determine current auth type
        current_auth = "key" if conn.get("ssh_key_path") else "password"
        auth_var = tk.StringVar(value=current_auth)
        ttk.Radiobutton(auth_frame, text="Password", variable=auth_var, value="password").pack(side="left")
        ttk.Radiobutton(auth_frame, text="Key File", variable=auth_var, value="key").pack(side="left")
        fields["auth_type"] = auth_var
        
        row += 1
        ttk.Label(dialog, text="Password:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        fields["password"] = ttk.Entry(dialog, width=25, show="*")
        fields["password"].grid(row=row, column=1, padx=5, pady=5)
        if conn.get("password"):
            fields["password"].insert(0, conn.get("password", ""))
        
        row += 1
        ttk.Label(dialog, text="Key File:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        key_frame = ttk.Frame(dialog)
        key_frame.grid(row=row, column=1, padx=5, pady=5)
        fields["key_path"] = ttk.Entry(key_frame, width=18)
        fields["key_path"].pack(side="left")
        fields["key_path"].insert(0, conn.get("ssh_key_path", ""))
        ttk.Button(key_frame, text="Browse", command=lambda: self.browse_file_entry(fields["key_path"])).pack(side="left", padx=2)
        
        def save_ssh_connection():
            # Save updated SSH connection
            config = {
                "connection_type": "ssh",
                "host": fields["host"].get(),
                "port": int(fields["port"].get() or 22),
                "database": "",  # SSH connections don't have database
                "username": fields["user"].get(),
                "password": fields["password"].get() if fields["auth_type"].get() == "password" else "",
                "ssh_key_path": fields["key_path"].get() if fields["auth_type"].get() == "key" else "",
            }
            
            new_name = fields["name"].get()
            if not new_name:
                messagebox.showerror("Error", "Connection name is required")
                return
            
            # Update the connection using ID
            if self.conn_manager.update_ssh_connection(original_id, new_name, config):
                dialog.destroy()
                self.load_connections_list()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=row + 1, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="Test SSH", command=lambda: self.test_ssh_from_dialog(fields)).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save", command=save_ssh_connection).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)
    
    def delete_odoo_connection(self):
        """Delete selected Odoo connection"""
        selection = self.odoo_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an Odoo connection to delete")
            return
        
        item = self.odoo_tree.item(selection[0])
        conn_name = item["text"]
        
        if messagebox.askyesno("Confirm", f"Delete Odoo connection '{conn_name}'?"):
            if self.conn_manager.delete_connection(conn_name):
                self.load_connections_list()
                self.refresh_connections()
    
    def delete_ssh_connection(self):
        """Delete selected SSH connection"""
        selection = self.ssh_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an SSH connection to delete")
            return
        
        item = self.ssh_tree.item(selection[0])
        conn_name = item["text"]
        
        if messagebox.askyesno("Confirm", f"Delete SSH connection '{conn_name}'?"):
            if self.conn_manager.delete_connection(conn_name):
                self.load_connections_list()
    
    def test_selected_connection(self, conn_type):
        """Test the selected connection"""
        if conn_type == "odoo":
            selection = self.odoo_tree.selection()
            if not selection:
                messagebox.showwarning("Warning", "Please select an Odoo connection to test")
                return
            
            item = self.odoo_tree.item(selection[0])
            conn_id = int(item["tags"][0]) if item["tags"] else None
            conn_name = item["text"]
            
            if not conn_id:
                messagebox.showerror("Error", "Could not get connection ID")
                return
            
            # Get connection and test it using ID
            conn = self.conn_manager.get_odoo_connection(conn_id)
            if conn:
                tool = OdooBackupRestore(conn_manager=self.conn_manager)
                config = {
                    "db_host": conn.get("host"),
                    "db_port": conn.get("port"),
                    "db_user": conn.get("username"),
                    "db_password": conn.get("password"),
                    "db_name": conn.get("database"),
                }
                success, msg = tool.test_connection(config)
                
                if success:
                    messagebox.showinfo("Success", f"Odoo database connection '{conn_name}' successful!")
                else:
                    messagebox.showerror("Error", f"Odoo connection '{conn_name}' failed: {msg}")
        
        elif conn_type == "ssh":
            selection = self.ssh_tree.selection()
            if not selection:
                messagebox.showwarning("Warning", "Please select an SSH connection to test")
                return
            
            item = self.ssh_tree.item(selection[0])
            conn_id = int(item["tags"][0]) if item["tags"] else None
            conn_name = item["text"]
            
            if not conn_id:
                messagebox.showerror("Error", "Could not get connection ID")
                return
            
            # Get connection details using ID
            conn = self.conn_manager.get_ssh_connection(conn_id)
            if not conn:
                messagebox.showerror("Error", f"Could not load connection: {conn_name}")
                return
            
            try:
                # Show progress (safely try to set cursor)
                try:
                    self.root.config(cursor="watch")
                    self.root.update()
                except:
                    pass  # Ignore cursor errors
                
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                connect_kwargs = {
                    "hostname": conn.get("host"),
                    "port": conn.get("port", 22),
                    "username": conn.get("username"),
                    "timeout": 10,  # Add timeout
                    "banner_timeout": 10,
                    "auth_timeout": 10,
                }
                
                # Use password or key authentication
                if conn.get("ssh_key_path"):
                    if os.path.exists(conn.get("ssh_key_path")):
                        connect_kwargs["key_filename"] = conn.get("ssh_key_path")
                    else:
                        messagebox.showerror("Error", f"SSH key file not found: {conn.get('ssh_key_path')}")
                        return
                elif conn.get("password"):
                    connect_kwargs["password"] = conn.get("password")
                else:
                    messagebox.showerror("Error", "No authentication method available (no password or key)")
                    return
                
                # Try to connect with timeout
                ssh.connect(**connect_kwargs)
                
                # Execute a simple command to verify connection with timeout
                stdin, stdout, stderr = ssh.exec_command("echo 'SSH connection test successful'", timeout=5)
                output = stdout.read().decode().strip()
                error = stderr.read().decode().strip()
                
                ssh.close()
                
                if "SSH connection test successful" in output:
                    messagebox.showinfo("Success", f"SSH connection '{conn_name}' successful!")
                elif error:
                    messagebox.showwarning("Warning", f"SSH connected but command failed:\n{error}")
                else:
                    messagebox.showwarning("Warning", f"SSH connection established but test command failed")
                    
            except paramiko.AuthenticationException as e:
                messagebox.showerror("Authentication Failed", f"SSH authentication failed for '{conn_name}':\n{str(e)}")
            except paramiko.SSHException as e:
                messagebox.showerror("SSH Error", f"SSH connection error for '{conn_name}':\n{str(e)}")
            except socket.timeout:
                messagebox.showerror("Timeout", f"SSH connection '{conn_name}' timed out after 10 seconds")
            except Exception as e:
                messagebox.showerror("Error", f"SSH connection '{conn_name}' failed:\n{str(e)}")
            finally:
                try:
                    self.root.config(cursor="")
                except:
                    pass  # Ignore cursor errors
    
    def test_ssh_from_dialog(self, fields):
        """Test SSH connection from dialog fields"""
        try:
            # Show progress (safely try to set cursor)
            try:
                self.root.config(cursor="watch")
                self.root.update()
            except:
                pass  # Ignore cursor errors
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                "hostname": fields["host"].get(),
                "port": int(fields["port"].get() or 22),
                "username": fields["user"].get(),
                "timeout": 10,  # Add 10 second timeout
                "banner_timeout": 10,  # Add banner timeout
                "auth_timeout": 10,  # Add auth timeout
            }
            
            if not connect_kwargs["hostname"]:
                messagebox.showerror("Error", "SSH host is required")
                return
            
            if not connect_kwargs["username"]:
                messagebox.showerror("Error", "SSH username is required")
                return
            
            if fields["auth_type"].get() == "password":
                password = fields["password"].get()
                if not password:
                    messagebox.showerror("Error", "Password is required for password authentication")
                    return
                connect_kwargs["password"] = password
            else:
                key_path = fields["key_path"].get()
                if not key_path:
                    messagebox.showerror("Error", "Key file path is required for key authentication")
                    return
                if not os.path.exists(key_path):
                    messagebox.showerror("Error", f"Key file not found: {key_path}")
                    return
                connect_kwargs["key_filename"] = key_path
            
            # Try to connect with timeout
            ssh.connect(**connect_kwargs)
            
            # Execute test command with timeout
            stdin, stdout, stderr = ssh.exec_command("echo 'SSH test OK'", timeout=5)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            
            ssh.close()
            
            if "SSH test OK" in output:
                messagebox.showinfo("Success", "SSH connection successful!")
            elif error:
                messagebox.showwarning("Warning", f"SSH connected but command failed:\n{error}")
            else:
                messagebox.showwarning("Warning", "SSH connected but no response from test command")
            
        except paramiko.AuthenticationException as e:
            messagebox.showerror("Authentication Failed", f"SSH authentication failed:\n{str(e)}")
        except paramiko.SSHException as e:
            messagebox.showerror("SSH Error", f"SSH connection error:\n{str(e)}")
        except socket.timeout:
            messagebox.showerror("Timeout", "SSH connection timed out after 10 seconds")
        except Exception as e:
            messagebox.showerror("Error", f"SSH connection failed:\n{str(e)}")
        finally:
            try:
                self.root.config(cursor="")
            except:
                pass  # Ignore cursor errors
    
    def refresh_connections(self):
        """Refresh connection dropdowns"""
        connections = self.conn_manager.list_connections()
        # Filter only Odoo connections for backup/restore
        # Store mapping of names to IDs
        self.odoo_conn_map = {}
        odoo_names = []
        for conn in connections:
            if conn['type'] == 'odoo':
                odoo_names.append(conn['name'])
                self.odoo_conn_map[conn['name']] = conn['id']

        self.source_combo["values"] = odoo_names
        self.dest_combo["values"] = odoo_names

    def load_connection(self, target):
        """Load selected connection details"""
        if target == "source":
            conn_name = self.source_conn.get()
            info_label = self.source_info_label
        else:
            conn_name = self.dest_conn.get()
            info_label = self.dest_info_label

        if not conn_name:
            return

        # Get Odoo connection by ID
        if hasattr(self, 'odoo_conn_map') and conn_name in self.odoo_conn_map:
            conn_id = self.odoo_conn_map[conn_name]
            conn = self.conn_manager.get_odoo_connection(conn_id)
            if conn:
                info = f"{conn['host']}:{conn['port']}/{conn['database']}"
                if conn.get("filestore_path"):
                    info += f"\nFilestore: {conn['filestore_path']}"
                info_label.config(text=info)


    def browse_backup_dir(self):
        """Browse for backup directory"""
        folder = filedialog.askdirectory()
        if folder:
            self.backup_dir_path.set(folder)
    
    def on_source_selected(self):
        """Handle source connection selection"""
        # Load connection details
        self.load_connection("source")
        
        # If in backup-only mode, set default backup filename
        if self.operation_mode.get() == "backup_only":
            conn_name = self.source_conn.get()
            if conn_name:
                # Generate timestamp
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Use configured backup directory
                default_dir = self.backup_directory
                
                # Create default filename
                default_filename = os.path.join(default_dir, f"backup_{conn_name}_{timestamp}.tar.gz")
                
                # Set the backup file path
                self.backup_file_var.set(default_filename)
    
    def update_operation_ui(self):
        """Update UI based on selected operation mode"""
        mode = self.operation_mode.get()
        
        # Hide all frames first
        self.backup_file_frame.pack_forget()
        self.restore_file_frame.pack_forget()
        self.source_frame.pack_forget()
        self.dest_frame.pack_forget()
        
        # Get the parent and find where to insert (after Operation Mode frame)
        # We need to re-pack in the correct order
        
        if mode == "backup_restore":
            # Show both source and destination
            self.source_frame.pack(fill="x", pady=5, after=self.mode_frame)
            self.dest_frame.pack(fill="x", pady=5, after=self.source_frame)
            self.execute_btn.config(text="Execute Backup & Restore")
        elif mode == "backup_only":
            # Show only source
            self.source_frame.pack(fill="x", pady=5, after=self.mode_frame)
            # Show backup file selector
            self.backup_file_frame.pack(side="left")
            self.execute_btn.config(text="Execute Backup")
            
            # If a source is already selected, set default filename
            conn_name = self.source_conn.get()
            if conn_name:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                default_dir = self.backup_directory
                default_filename = os.path.join(default_dir, f"backup_{conn_name}_{timestamp}.tar.gz")
                self.backup_file_var.set(default_filename)
        elif mode == "restore_only":
            # Show only destination  
            self.dest_frame.pack(fill="x", pady=5, after=self.mode_frame)
            # Show restore file selector
            self.restore_file_frame.pack(side="left")
            self.execute_btn.config(text="Execute Restore")
            # Refresh available restore files for the selected destination
            self.refresh_restore_files()
    
    def on_dest_selected(self):
        """Handle destination connection selection"""
        # Load the connection details
        self.load_connection("dest")
        
        # If in restore_only mode, refresh the restore files dropdown
        if self.operation_mode.get() == "restore_only":
            self.refresh_restore_files()
    
    def refresh_restore_files(self):
        """Refresh the list of all available backup files for restore dropdown"""
        # Get list of ALL backup files (full paths)
        backup_files = self.get_all_backup_files()
        
        # Show only filenames in the dropdown
        filenames = [os.path.basename(f) for f in backup_files]
        self.restore_file_combo['values'] = filenames
        
        # Store the mapping of filename to full path
        self.restore_file_mapping = {os.path.basename(f): f for f in backup_files}
        
        # If there are files and nothing is selected, select the most recent
        if filenames and not self.restore_file_var.get():
            self.restore_file_var.set(filenames[0])
    
    def get_all_backup_files(self):
        """Get list of all backup files in the backup directory"""
        backup_files = []
        
        # Look for all backup files in the backup directory
        if os.path.exists(self.backup_directory):
            for filename in os.listdir(self.backup_directory):
                # Check for .tar.gz and .zip backup files
                if (filename.startswith("backup_") and filename.endswith('.tar.gz')) or \
                   (filename.endswith('.zip') and "backup" in filename.lower()):
                    full_path = os.path.join(self.backup_directory, filename)
                    if os.path.isfile(full_path):
                        backup_files.append(full_path)
        
        # Sort files by modification time (newest first)
        backup_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        
        return backup_files
    
    def browse_backup_file(self):
        """Browse for backup zip file location"""
        filename = filedialog.asksaveasfilename(
            initialdir=self.backup_directory,
            defaultextension=".tar.gz",
            filetypes=[("TAR.GZ files", "*.tar.gz"), ("ZIP files", "*.zip"), ("All files", "*.*")],
            title="Save backup as..."
        )
        if filename:
            self.backup_file_var.set(filename)
    
    def browse_restore_file(self):
        """Browse for restore zip file"""
        filename = filedialog.askopenfilename(
            initialdir=self.backup_directory,
            filetypes=[("TAR.GZ files", "*.tar.gz"), ("ZIP files", "*.zip"), ("All files", "*.*")],
            title="Select backup file to restore..."
        )
        if filename:
            # If the file is in the backup directory, store just the filename
            if os.path.dirname(filename) == self.backup_directory:
                basename = os.path.basename(filename)
                self.restore_file_var.set(basename)
                # Add to mapping
                self.restore_file_mapping[basename] = filename
            else:
                # Store full path for files outside backup directory
                self.restore_file_var.set(filename)

    def test_connection(self, target):
        """Test selected connection"""
        if target == "source":
            conn_name = self.source_conn.get()
        else:
            conn_name = self.dest_conn.get()

        if not conn_name:
            messagebox.showwarning("Warning", f"Please select a {target} connection")
            return

        # Get connection by ID
        if not hasattr(self, 'odoo_conn_map') or conn_name not in self.odoo_conn_map:
            messagebox.showerror("Error", f"Connection '{conn_name}' not found")
            return
        
        conn_id = self.odoo_conn_map[conn_name]
        conn = self.conn_manager.get_odoo_connection(conn_id)
        if not conn:
            return

        config = {
            "db_host": conn["host"],
            "db_port": conn["port"],
            "db_user": conn["username"],
            "db_password": conn["password"],
            "db_name": conn["database"],
        }

        tool = OdooBackupRestore(conn_manager=self.conn_manager)
        success, msg = tool.test_connection(config)

        if success:
            messagebox.showinfo("Success", f"{target.title()} connection successful!")
            self.log_message(f"{target.title()} connection test successful", "success")
        else:
            messagebox.showerror("Error", f"{target.title()} connection failed: {msg}")
            self.log_message(f"{target.title()} connection test failed: {msg}", "error")

    def log_message(self, message, level="info"):
        """Add message to log"""
        self.log_text.insert(
            tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n", level
        )
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def clear_log(self):
        """Clear log text"""
        self.log_text.delete(1.0, tk.END)

    def update_progress(self, value, message=""):
        """Update progress bar"""
        self.progress_bar["value"] = value
        if message:
            self.progress_label.config(text=message)
        self.root.update_idletasks()

    def execute_operation(self):
        """Execute the selected operation (backup, restore, or both)"""
        mode = self.operation_mode.get()
        
        if mode == "backup_restore":
            self.execute_backup_restore()
        elif mode == "backup_only":
            self.execute_backup_only()
        elif mode == "restore_only":
            self.execute_restore_only()
    
    def execute_backup_only(self):
        """Execute backup only to zip file"""
        source_name = self.source_conn.get()
        backup_file = self.backup_file_var.get()
        
        if not source_name:
            messagebox.showerror("Error", "Please select a source connection")
            return
        
        if not backup_file:
            messagebox.showerror("Error", "Please specify where to save the backup")
            return
        
        # Get source connection by ID
        if not hasattr(self, 'odoo_conn_map') or source_name not in self.odoo_conn_map:
            messagebox.showerror("Error", "Source connection not found")
            return
        
        source_conn_id = self.odoo_conn_map[source_name]
        source_conn = self.conn_manager.get_odoo_connection(source_conn_id)
        
        if not source_conn:
            messagebox.showerror("Error", "Failed to load source connection details")
            return
        
        # Prepare source configuration
        source_config = {
            "db_host": source_conn["host"],
            "db_port": source_conn["port"],
            "db_user": source_conn["username"],
            "db_password": source_conn["password"],
            "db_name": source_conn["database"],
            "filestore_path": source_conn["filestore_path"],
            "odoo_version": source_conn.get("odoo_version", ""),
            "db_only": self.db_only.get(),
            "filestore_only": self.filestore_only.get(),
            "verbose": self.verbose.get(),
            "use_ssh": source_conn.get("use_ssh", False),
            "ssh_connection_id": source_conn.get("ssh_connection_id"),
        }
        
        # Execute backup in thread
        def run_backup():
            try:
                self.log_message("Starting backup operation...", "info")
                # Create tool with callbacks
                tool = OdooBackupRestore(
                    progress_callback=lambda val, msg: self.update_progress(val, msg),
                    log_callback=lambda msg, level: self.log_message(msg, level),
                    conn_manager=self.conn_manager
                )
                
                # Create backup
                self.log_message(f"Creating backup of {source_conn['database']}...", "info")
                backup_path = tool.backup(source_config)
                
                if backup_path:
                    # Move/rename to the specified file
                    import shutil
                    shutil.move(backup_path, backup_file)
                    self.log_message(f"Backup saved to: {backup_file}", "success")
                    messagebox.showinfo("Success", f"Backup completed successfully!\nSaved to: {backup_file}")
                else:
                    self.log_message("Backup failed", "error")
                    messagebox.showerror("Error", "Backup operation failed")
                    
            except Exception as e:
                error_msg = str(e)
                self.log_message(f"Error: {error_msg}", "error")
                messagebox.showerror("Error", f"Backup failed:\n{error_msg}")
            finally:
                self.progress_bar.stop()
                self.execute_btn.config(state="normal")
        
        # Start backup in thread
        self.execute_btn.config(state="disabled")
        self.progress_bar.start()
        threading.Thread(target=run_backup, daemon=True).start()
    
    def execute_restore_only(self):
        """Execute restore only from zip file"""
        dest_name = self.dest_conn.get()
        restore_file = self.restore_file_var.get()
        
        if not dest_name:
            messagebox.showerror("Error", "Please select a destination connection")
            return
        
        if not restore_file:
            messagebox.showerror("Error", "Please select a backup file to restore")
            return
        
        # Get the full path from the mapping if it's just a filename
        if restore_file in self.restore_file_mapping:
            restore_file = self.restore_file_mapping[restore_file]
        elif not os.path.isabs(restore_file):
            # If it's not in mapping and not absolute, prepend backup directory
            restore_file = os.path.join(self.backup_directory, restore_file)
        
        if not os.path.exists(restore_file):
            messagebox.showerror("Error", f"Backup file not found: {restore_file}")
            return
        
        # Get destination connection by ID
        if not hasattr(self, 'odoo_conn_map') or dest_name not in self.odoo_conn_map:
            messagebox.showerror("Error", "Destination connection not found")
            return
        
        dest_conn_id = self.odoo_conn_map[dest_name]
        dest_conn = self.conn_manager.get_odoo_connection(dest_conn_id)
        
        if not dest_conn:
            messagebox.showerror("Error", "Failed to load destination connection details")
            return
        
        # Prepare destination configuration
        dest_config = {
            "db_host": dest_conn["host"],
            "db_port": dest_conn["port"],
            "db_user": dest_conn["username"],
            "db_password": dest_conn["password"],
            "db_name": dest_conn["database"],
            "filestore_path": dest_conn["filestore_path"],
            "odoo_version": dest_conn.get("odoo_version", ""),
            "db_only": self.db_only.get(),
            "filestore_only": self.filestore_only.get(),
            "verbose": self.verbose.get(),
        }
        
        # Create custom confirmation dialog
        confirm_dialog = tk.Toplevel(self.root)
        confirm_dialog.title("Confirm Restore")
        confirm_dialog.transient(self.root)
        confirm_dialog.grab_set()
        
        # Center the dialog
        confirm_dialog.geometry("450x300")
        window_width = 450
        window_height = 300
        screen_width = confirm_dialog.winfo_screenwidth()
        screen_height = confirm_dialog.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        confirm_dialog.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Create the message
        msg_frame = ttk.Frame(confirm_dialog, padding="20")
        msg_frame.pack(fill="both", expand=True)
        
        ttk.Label(msg_frame, text="Are you sure you want to restore?", 
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 10))
        
        ttk.Label(msg_frame, text=f"Backup file: {os.path.basename(restore_file)}").pack(anchor="w", pady=2)
        ttk.Label(msg_frame, text=f"Destination: {dest_name}").pack(anchor="w", pady=2)
        
        ttk.Separator(msg_frame, orient="horizontal").pack(fill="x", pady=10)
        
        ttk.Label(msg_frame, text="This will:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(0, 5))
        ttk.Label(msg_frame, text=f"• Drop and recreate database: {dest_config['db_name']}").pack(anchor="w", padx=(20, 0), pady=2)
        
        if not dest_config.get('filestore_only', False) and dest_config.get('filestore_path'):
            ttk.Label(msg_frame, text=f"• Replace filestore at: {dest_config['filestore_path']}").pack(anchor="w", padx=(20, 0), pady=2)
            ttk.Label(msg_frame, text="  (Existing filestore will be backed up)", 
                     font=("TkDefaultFont", 8, "italic")).pack(anchor="w", padx=(20, 0), pady=2)
        
        # Result variable
        result = {"confirmed": False}
        
        def on_yes():
            result["confirmed"] = True
            confirm_dialog.destroy()
        
        def on_no():
            confirm_dialog.destroy()
        
        # Button frame
        btn_frame = ttk.Frame(confirm_dialog)
        btn_frame.pack(side="bottom", pady=20)
        
        ttk.Button(btn_frame, text="Yes", command=on_yes, width=12).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="No", command=on_no, width=12).pack(side="left", padx=10)
        
        # Wait for dialog to close
        self.root.wait_window(confirm_dialog)
        
        if not result["confirmed"]:
            return
        
        # Execute restore in thread
        def run_restore():
            try:
                self.log_message("Starting restore operation...", "info")
                # Create tool with callbacks
                tool = OdooBackupRestore(
                    progress_callback=lambda val, msg: self.update_progress(val, msg),
                    log_callback=lambda msg, level: self.log_message(msg, level),
                    conn_manager=self.conn_manager
                )
                
                # Restore from backup file
                self.log_message(f"Restoring from {restore_file} to {dest_conn['database']}...", "info")
                success = tool.restore(dest_config, restore_file)
                
                if success:
                    self.log_message("Restore completed successfully!", "success")
                    messagebox.showinfo("Success", "Restore completed successfully!")
                else:
                    self.log_message("Restore failed", "error")
                    messagebox.showerror("Error", "Restore operation failed")
                    
            except Exception as e:
                error_msg = str(e)
                self.log_message(f"Error: {error_msg}", "error")
                messagebox.showerror("Error", f"Restore failed:\n{error_msg}")
            finally:
                self.progress_bar.stop()
                self.execute_btn.config(state="normal")
        
        # Start restore in thread
        self.execute_btn.config(state="disabled")
        self.progress_bar.start()
        threading.Thread(target=run_restore, daemon=True).start()

    def execute_backup_restore(self):
        """Execute backup and restore operation"""
        # Get source and destination connections
        source_name = self.source_conn.get()
        dest_name = self.dest_conn.get()

        if not source_name or not dest_name:
            messagebox.showerror(
                "Error", "Please select both source and destination connections"
            )
            return

        # Get connections by ID
        if not hasattr(self, 'odoo_conn_map'):
            messagebox.showerror("Error", "No connections available")
            return
        
        if source_name not in self.odoo_conn_map or dest_name not in self.odoo_conn_map:
            messagebox.showerror("Error", "Failed to find connection details")
            return
        
        source_conn_id = self.odoo_conn_map[source_name]
        dest_conn_id = self.odoo_conn_map[dest_name]
        
        source_conn = self.conn_manager.get_odoo_connection(source_conn_id)
        dest_conn = self.conn_manager.get_odoo_connection(dest_conn_id)

        if not source_conn or not dest_conn:
            messagebox.showerror("Error", "Failed to load connection details")
            return

        # Prepare configurations
        source_config = {
            "db_host": source_conn["host"],
            "db_port": source_conn["port"],
            "db_user": source_conn["username"],
            "db_password": source_conn["password"],
            "db_name": source_conn["database"],
            "filestore_path": source_conn["filestore_path"],
            "odoo_version": source_conn.get("odoo_version", ""),
            "db_only": self.db_only.get(),
            "verbose": self.verbose.get(),
            "save_backup": self.save_backup.get(),
            "backup_dir": (
                self.backup_dir_path.get() if self.save_backup.get() else None
            ),
            "use_ssh": source_conn.get("use_ssh", False),
            "ssh_connection_id": source_conn.get("ssh_connection_id"),
        }

        dest_config = {
            "db_host": dest_conn["host"],
            "db_port": dest_conn["port"],
            "db_user": dest_conn["username"],
            "db_password": dest_conn["password"],
            "db_name": dest_conn["database"],
            "filestore_path": dest_conn["filestore_path"],
            "db_only": self.db_only.get(),
            "filestore_only": self.filestore_only.get(),
            "verbose": self.verbose.get(),
        }

        # Confirm operation
        msg = f"This will:\n"
        msg += f"1. Backup from: {source_conn['host']}/{source_conn['database']}\n"
        msg += f"2. Restore to: {dest_conn['host']}/{dest_conn['database']}\n"
        msg += "\n⚠️ Warning: This will OVERWRITE the destination database!"

        if not messagebox.askyesno("Confirm Operation", msg):
            return

        # Disable execute button
        self.execute_btn.config(state="disabled")
        self.clear_log()

        # Run in thread
        thread = threading.Thread(
            target=self.run_backup_restore, args=(source_config, dest_config)
        )
        thread.daemon = True
        thread.start()

    def run_backup_restore(self, source_config, dest_config):
        """Run backup and restore in thread"""
        try:
            tool = OdooBackupRestore(
                progress_callback=lambda v, m: self.root.after(
                    0, self.update_progress, v, m
                ),
                log_callback=lambda m, l: self.root.after(0, self.log_message, m, l),
                conn_manager=self.conn_manager
            )

            # Check dependencies
            tool.check_dependencies()

            # Execute backup and restore
            tool.backup_and_restore(source_config, dest_config)

            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Success",
                    f"✅ Backup and restore completed successfully!\n\n"
                    f"Source: {source_config['db_name']}\n"
                    f"Destination: {dest_config['db_name']}",
                ),
            )

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(
                0, lambda: self.log_message(f"Operation failed: {str(e)}", "error")
            )

        finally:
            self.root.after(0, lambda: self.execute_btn.config(state="normal"))


def main():
    # Check if cryptography is installed
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print("Error: cryptography module is required for connection management")
        print("Install it with: pip install cryptography")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Odoo Database and Filestore Backup/Restore Tool with Connection Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--gui", action="store_true", help="Launch GUI interface (requires tkinter)"
    )

    args = parser.parse_args()

    # Launch GUI
    if not TKINTER_AVAILABLE:
        print("❌ Error: tkinter is not installed!")
        print("Install tkinter to use this tool:")
        print("  Ubuntu/Debian: sudo apt-get install python3-tk")
        print("  RHEL/CentOS: sudo dnf install python3-tkinter")
        sys.exit(1)

    root = tk.Tk()
    app = OdooBackupRestoreGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
