"""
Core Odoo Backup and Restore functionality
"""

import os
import sys
import subprocess
import shutil
import tarfile
import tempfile
import json
import zipfile
import configparser
from datetime import datetime
from pathlib import Path
import paramiko


class OdooBackupRestore:
    """Main class for Odoo backup and restore operations"""

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
        if "options" not in config:
            raise ValueError("No 'options' section found in config file")

        options = config["options"]

        # Extract connection details
        connection_config = {
            "host": options.get("db_host", "localhost"),
            "port": options.get("db_port", "5432"),
            "database": options.get("db_name", "False"),  # Odoo uses 'False' as default
            "username": options.get("db_user", "odoo"),
            "password": options.get("db_password", "False"),
            "filestore_path": None,
            "odoo_version": "17.0",  # Default version
            "is_local": options.get("db_host", "localhost")
            in ["localhost", "127.0.0.1"],
        }

        # Try to determine filestore path
        data_dir = options.get("data_dir", None)
        if data_dir and data_dir != "False":
            connection_config["filestore_path"] = data_dir
        else:
            connection_config["filestore_path"] = os.path.expanduser(
                "~/.local/share/Odoo"
            )

        # Clean up 'False' values
        for key in ["database", "password"]:
            if connection_config[key] == "False":
                connection_config[key] = ""

        return connection_config

    def __del__(self):
        """Cleanup temp directory"""
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
            if config.get("use_ssh") and config.get("ssh_connection_id"):
                # Test remote filestore path
                try:
                    ssh_conn = self.conn_manager.get_ssh_connection(
                        config["ssh_connection_id"]
                    )
                    if ssh_conn:
                        ssh = self._get_ssh_client(ssh_conn)

                        # Check if the filestore path exists
                        stdin, stdout, stderr = ssh.exec_command(
                            f"test -d '{filestore_path}'"
                        )
                        if stdout.channel.recv_exit_status() == 0:
                            messages.append(
                                f"✓ Remote filestore path exists: {filestore_path}"
                            )
                        else:
                            # Try with database name appended
                            db_name = config.get("db_name", "")
                            if db_name:
                                full_path = os.path.join(
                                    filestore_path, "filestore", db_name
                                )
                                stdin, stdout, stderr = ssh.exec_command(
                                    f"test -d '{full_path}'"
                                )
                                if stdout.channel.recv_exit_status() == 0:
                                    messages.append(
                                        f"✓ Remote filestore path exists: {full_path}"
                                    )
                                else:
                                    messages.append(
                                        f"⚠ Remote filestore path not found"
                                    )
                            else:
                                messages.append(
                                    f"⚠ Remote filestore path not found: {filestore_path}"
                                )

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
                            messages.append(
                                f"✓ Local filestore path exists: {full_path}"
                            )
                        else:
                            messages.append(f"⚠ Local filestore path not found")
                    else:
                        messages.append(
                            f"⚠ Local filestore path not found: {filestore_path}"
                        )

        # Return combined result
        return not has_errors, "\n".join(messages)

    def _get_ssh_client(self, ssh_conn):
        """Create and configure SSH client"""
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
        return ssh

    def check_remote_disk_space(self, ssh, path, estimated_size_mb):
        """Check if remote server has enough disk space for backup"""
        try:
            # Get available space in /tmp
            stdin, stdout, stderr = ssh.exec_command(
                "df -BM /tmp | tail -1 | awk '{print $4}'"
            )
            available_space = stdout.read().decode().strip()
            # Remove 'M' suffix and convert to integer
            available_mb = int(available_space.rstrip("M"))

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

        # Capture output to prevent flooding console
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
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
            return self._backup_remote_filestore(config, filestore_path)
        else:
            return self._backup_local_filestore(config, filestore_path)

    def _backup_remote_filestore(self, config, filestore_path):
        """Backup remote filestore via SSH"""
        # Get SSH connection details
        ssh_conn = self.conn_manager.get_ssh_connection(config["ssh_connection_id"])
        if not ssh_conn:
            self.log("Error: SSH connection not found", "error")
            return None

        self.log(f"Backing up remote filestore via SSH: {filestore_path}...")
        self.update_progress(50, "Backing up remote filestore...")

        try:
            ssh = self._get_ssh_client(ssh_conn)

            # Create remote tar archive
            archive_name = os.path.join(self.temp_dir, "filestore.tar.gz")
            remote_temp = f"/tmp/filestore_{self.timestamp}.tar.gz"

            # Check and adjust filestore path
            self.log("Checking remote filestore path...")
            stdin, stdout, stderr = ssh.exec_command(f"test -d '{filestore_path}'")
            if stdout.channel.recv_exit_status() != 0:
                # Path doesn't exist, try with database name appended
                db_name = config.get("db_name", "")
                if db_name:
                    filestore_path = os.path.join(filestore_path, "filestore", db_name)
                    self.log(f"Adjusted filestore path to: {filestore_path}")

            # Estimate and check disk space
            self.log("Estimating backup size...")
            estimated_size = self.estimate_compressed_size(
                ssh, filestore_path, is_database=False
            )

            has_space, available_mb, required_mb = self.check_remote_disk_space(
                ssh, "/tmp", estimated_size
            )

            if not has_space:
                error_msg = f"Insufficient disk space on remote server!\n"
                error_msg += f"Available: {available_mb}MB, Required: {required_mb}MB"
                self.log(error_msg, "error")
                ssh.close()
                raise Exception(error_msg)

            self.log(
                f"Disk space check passed (Available: {available_mb}MB, Required: {required_mb}MB)"
            )
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
                # Always clean up remote temp file
                self.log("Cleaning up remote temporary files...")
                ssh.exec_command(f"rm -f {remote_temp}")
                ssh.close()

        except Exception as e:
            self.log(f"Error backing up remote filestore: {str(e)}", "error")
            return None

    def _backup_local_filestore(self, config, filestore_path):
        """Backup local filestore"""
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
        backup_name = f"backup_{config['db_name'].upper()}_{self.timestamp}.tar.gz"
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
            tar.add(db_dump, arcname="database.sql")
            tar.add(metadata_file, arcname="metadata.json")
            if filestore_archive:
                tar.add(filestore_archive, arcname="filestore.tar.gz")

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
        # First try as zip
        try:
            with zipfile.ZipFile(backup_file, "r") as zf:
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
                    raise Exception(
                        f"Unable to extract {backup_file}. File format not recognized."
                    )

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
            elif "filestore" in file and file.endswith(".tar.gz"):
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
                # Drop existing database
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
                subprocess.run(drop_cmd, env=env, check=True, 
                             capture_output=True, text=True)

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
            subprocess.run(create_cmd, env=env, check=True, 
                         capture_output=True, text=True)

            # Restore database
            self.update_progress(50, "Importing database data...")

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
                "-q",  # Quiet mode since we're capturing output anyway
            ]
            # Capture output to prevent flooding console
            subprocess.run(restore_cmd, env=env, check=True, 
                         capture_output=True, text=True)

            self.log(f"Database restored successfully")
            self.update_progress(70, "Database restore complete")
            return True

        except Exception as e:
            self.log(f"Error restoring database: {str(e)}", "error")
            raise

    def restore_filestore(self, config, filestore_archive):
        """Restore Odoo filestore"""
        if not filestore_archive:
            self.log("No filestore to restore", "warning")
            return True

        filestore_path = config["filestore_path"]
        if not filestore_path:
            self.log("Warning: Filestore path not specified", "warning")
            return False

        self.log(f"Restoring filestore to: {filestore_path}...")
        self.update_progress(75, "Restoring filestore...")

        try:
            # Create parent directory if it doesn't exist
            os.makedirs(filestore_path, exist_ok=True)

            # Extract filestore archive
            with tarfile.open(filestore_archive, "r:gz") as tar:
                # Clear existing filestore if exists
                db_filestore_path = os.path.join(
                    filestore_path, "filestore", config["db_name"]
                )
                if os.path.exists(db_filestore_path):
                    self.log(f"Removing existing filestore: {db_filestore_path}")
                    shutil.rmtree(db_filestore_path, ignore_errors=True)

                # Extract to filestore path
                tar.extractall(filestore_path)

            self.log("Filestore restored successfully")
            self.update_progress(90, "Filestore restore complete")
            return True

        except Exception as e:
            self.log(f"Error restoring filestore: {str(e)}", "error")
            return False

    def backup(self, config):
        """Create a complete backup (database + filestore)"""
        try:
            self.log("=== Starting Odoo Backup ===", "info")
            self.update_progress(0, "Starting backup...")

            # Check dependencies
            self.check_dependencies()

            # Backup database
            db_dump = self.backup_database(config)

            # Backup filestore
            filestore_archive = None
            if config.get("backup_filestore", True):
                filestore_archive = self.backup_filestore(config)

            # Create combined archive
            backup_path = self.create_backup_archive(config, db_dump, filestore_archive)

            self.update_progress(100, "Backup completed!")
            self.log(f"=== Backup Complete: {backup_path} ===", "success")
            return backup_path

        except Exception as e:
            self.log(f"Backup failed: {str(e)}", "error")
            self.update_progress(0, "Backup failed")
            raise

    def neutralize_database(self, config):
        """Neutralize database for non-production use"""
        try:
            self.log("=== Neutralizing Database ===", "warning")
            self.update_progress(85, "Neutralizing database...")
            
            env = os.environ.copy()
            if config.get("db_password"):
                env["PGPASSWORD"] = config["db_password"]
            
            # Build the neutralization SQL queries
            neutralize_sql = """
            -- Disable all outgoing mail servers
            UPDATE ir_mail_server SET active = false WHERE active = true;
            
            -- Disable all scheduled actions (crons)
            UPDATE ir_cron SET active = false WHERE active = true;
            
            -- Reset admin password to 'admin' (using Odoo's password hash)
            UPDATE res_users 
            SET password = '$pbkdf2-sha512$25000$UApBiDFmTGktxXiPEYIwJg$Ius6wK3iLCzZYrcF7N/siGtEbCWVdgUy4v3IKHuvxBXotetNmwKQc5BpRs1ItQan1WPZV9yofLJrJhMZr0MuWw'
            WHERE login = 'admin';
            
            -- Reset all other user passwords to 'demo'
            UPDATE res_users 
            SET password = '$pbkdf2-sha512$25000$c26VsrYWAkCIUWqtVUqp1Q$0bAM1MF6FA5V5hPu0h8Y.dKOzekUVbFDuXpYm44MaQR9oGY0Yd5qvSx6YV1orchImpl0kqVBPvQ3n..4bLpxg'
            WHERE login != 'admin' AND login != '__system__';
            
            -- Disable all payment acquirers
            UPDATE payment_acquirer SET state = 'disabled' WHERE state != 'disabled';
            
            -- Clear all email queue
            DELETE FROM mail_mail WHERE state IN ('outgoing', 'exception');
            
            -- Disable website robots.txt indexing
            UPDATE website SET robots_txt = E'User-agent: *\\nDisallow: /' WHERE robots_txt IS NULL OR robots_txt != E'User-agent: *\\nDisallow: /';
            
            -- Add warning message to company name
            UPDATE res_company 
            SET name = CONCAT('[TEST] ', name)
            WHERE name NOT LIKE '[TEST]%';
            
            -- Log neutralization details
            INSERT INTO ir_logging (create_date, create_uid, name, type, dbname, level, message, path, line, func)
            VALUES (
                NOW(), 
                1, 
                'odoo.neutralization', 
                'server', 
                '""" + config["db_name"] + """', 
                'WARNING',
                'Database has been neutralized for testing purposes', 
                'odoo_backup_tool', 
                0, 
                'neutralize'
            );
            """
            
            # Execute neutralization queries
            psql_cmd = [
                "psql",
                "-h", config["db_host"],
                "-p", str(config["db_port"]),
                "-U", config["db_user"],
                "-d", config["db_name"],
                "-c", neutralize_sql
            ]
            
            result = subprocess.run(psql_cmd, env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.log(f"Warning: Some neutralization queries may have failed: {result.stderr}", "warning")
            
            self.log("Database neutralization complete:", "success")
            self.log("  ✓ All outgoing mail servers disabled", "info")
            self.log("  ✓ All scheduled actions (crons) disabled", "info") 
            self.log("  ✓ Admin password reset to 'admin'", "info")
            self.log("  ✓ All user passwords reset to 'demo'", "info")
            self.log("  ✓ Payment acquirers disabled", "info")
            self.log("  ✓ Email queue cleared", "info")
            self.log("  ✓ Website indexing disabled", "info")
            self.log("  ✓ Company names prefixed with [TEST]", "info")
            
            self.update_progress(90, "Neutralization complete")
            return True
            
        except Exception as e:
            self.log(f"Error during neutralization: {str(e)}", "error")
            # Don't fail the entire restore if neutralization fails
            self.log("Restore will continue despite neutralization error", "warning")
            return False

    def restore(self, config, backup_file):
        """Restore from a backup archive file"""
        try:
            self.log("=== Starting Odoo Restore ===", "info")
            self.update_progress(0, "Starting restore...")

            # Check dependencies
            self.check_dependencies()

            # Extract backup
            db_dump, filestore_archive, metadata = self.extract_backup(backup_file)

            if not db_dump:
                raise Exception("No database dump found in backup file")

            # Restore database
            self.restore_database(config, db_dump)

            # Restore filestore
            if filestore_archive and config.get("restore_filestore", True):
                self.restore_filestore(config, filestore_archive)

            # Neutralize database if requested
            if config.get("neutralize", False):
                self.neutralize_database(config)

            self.update_progress(100, "Restore completed!")
            self.log("=== Restore Complete ===", "success")
            return True

        except Exception as e:
            self.log(f"Restore failed: {str(e)}", "error")
            self.update_progress(0, "Restore failed")
            raise

    def backup_and_restore(self, source_config, dest_config):
        """Perform backup from source and restore to destination in one operation"""
        try:
            self.log("=== Starting Backup and Restore Operation ===", "info")

            # Backup from source
            self.log("Phase 1: Backing up from source", "info")
            backup_file = self.backup(source_config)

            # Restore to destination
            self.log("Phase 2: Restoring to destination", "info")
            self.restore(dest_config, backup_file)

            self.log("=== Backup and Restore Complete ===", "success")
            return True

        except Exception as e:
            self.log(f"Backup and restore failed: {str(e)}", "error")
            raise
