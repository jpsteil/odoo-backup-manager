"""Dialog for creating/editing Docker export profiles"""

import json
import tkinter as tk
from tkinter import ttk, messagebox


class DockerExportDialog(tk.Toplevel):
    """Dialog for managing Docker export profiles"""

    def __init__(self, parent, title, conn_manager, profile_data=None):
        """
        Args:
            parent: Parent window
            title: Dialog title
            conn_manager: ConnectionManager instance
            profile_data: Existing profile data for editing (None for new)
        """
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        self.conn_manager = conn_manager
        self.profile_data = profile_data
        self.is_edit = profile_data is not None
        self.result = None

        # Make dialog modal
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.create_widgets()

        if self.is_edit:
            self.load_profile_data()

        self.center_window()
        self.name_entry.focus_set()

    def center_window(self):
        """Center dialog on parent window"""
        self.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        dialog_width = self.winfo_width()
        dialog_height = self.winfo_height()
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(10, min(x, screen_width - dialog_width - 10))
        y = max(10, min(y, screen_height - dialog_height - 10))
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """Create dialog widgets"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        row = 0

        # Profile Name
        ttk.Label(main_frame, text="Profile Name:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.name_entry = ttk.Entry(main_frame, width=40)
        self.name_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        row += 1

        # Odoo Connection
        ttk.Label(main_frame, text="Odoo Connection:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.odoo_conn_map = {}
        connections = self.conn_manager.list_connections()
        odoo_names = []
        for c in connections:
            if c["type"] == "odoo":
                odoo_names.append(c["name"])
                self.odoo_conn_map[c["name"]] = c["id"]

        self.conn_combo = ttk.Combobox(
            main_frame, values=odoo_names, state="readonly", width=37
        )
        self.conn_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        if odoo_names:
            self.conn_combo.current(0)
        row += 1

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Source Settings header
        ttk.Label(main_frame, text="Source Server Settings", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )
        row += 1

        # Source Base Directory
        ttk.Label(main_frame, text="Source Base Dir:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.source_dir_entry = ttk.Entry(main_frame, width=40)
        self.source_dir_entry.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.source_dir_entry.insert(0, "/home/administrator/qlf")
        row += 1

        # Subdirectories
        ttk.Label(main_frame, text="Subdirectories:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.subdirs_entry = ttk.Entry(main_frame, width=40)
        self.subdirs_entry.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.subdirs_entry.insert(0, "odoo,qlf-odoo,LIMS17")
        row += 1

        # Python Venv Path
        ttk.Label(main_frame, text="Python Venv Path:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.venv_entry = ttk.Entry(main_frame, width=40)
        self.venv_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        self.venv_entry.insert(0, "/home/administrator/venv/odoo")
        row += 1

        # Extra Files
        ttk.Label(main_frame, text="Extra Files:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.extra_files_entry = ttk.Entry(main_frame, width=40)
        self.extra_files_entry.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.extra_files_entry.insert(0, "full_update.sh")
        row += 1

        # odoo.conf relative path
        ttk.Label(main_frame, text="odoo.conf Path:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.conf_path_entry = ttk.Entry(main_frame, width=40)
        self.conf_path_entry.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.conf_path_entry.insert(0, "odoo/odoo.conf")
        row += 1

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Docker Settings header
        ttk.Label(
            main_frame, text="Docker Container Settings", font=("", 9, "bold")
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 2))
        row += 1

        # Container Base Dir
        ttk.Label(main_frame, text="Container Base Dir:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.container_dir_entry = ttk.Entry(main_frame, width=40)
        self.container_dir_entry.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.container_dir_entry.insert(0, "/opt/odoo/qlf")
        row += 1

        # PostgreSQL Version and Python Version on same row
        ttk.Label(main_frame, text="PostgreSQL Version:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        version_frame = ttk.Frame(main_frame)
        version_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)

        self.pg_version_combo = ttk.Combobox(
            version_frame, values=["17", "16", "15", "14"], state="readonly", width=5
        )
        self.pg_version_combo.set("16")
        self.pg_version_combo.pack(side="left")

        ttk.Label(version_frame, text="   Python Version:").pack(side="left")
        self.py_version_combo = ttk.Combobox(
            version_frame,
            values=["3.12", "3.11", "3.10"],
            state="readonly",
            width=5,
        )
        self.py_version_combo.set("3.12")
        self.py_version_combo.pack(side="left")
        row += 1

        # Ports on same row
        ttk.Label(main_frame, text="Odoo Port:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        ports_frame = ttk.Frame(main_frame)
        ports_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)

        self.odoo_port_entry = ttk.Entry(ports_frame, width=8)
        self.odoo_port_entry.insert(0, "8069")
        self.odoo_port_entry.pack(side="left")

        ttk.Label(ports_frame, text="   Mailpit Port:").pack(side="left")
        self.mailpit_port_entry = ttk.Entry(ports_frame, width=8)
        self.mailpit_port_entry.insert(0, "8025")
        self.mailpit_port_entry.pack(side="left")
        row += 1

        # Separator
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Custom Neutralization SQL
        ttk.Label(main_frame, text="Custom Neutralize SQL:").grid(
            row=row, column=0, sticky="nw", pady=2
        )
        self.custom_sql_text = tk.Text(main_frame, width=40, height=4)
        self.custom_sql_text.grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        row += 1

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(10, 0))

        ttk.Button(btn_frame, text="Save", command=self.save_profile).pack(
            side="left", padx=5
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="left", padx=5
        )

        # Keyboard bindings
        self.bind("<Return>", lambda e: self.save_profile())
        self.bind("<Escape>", lambda e: self.destroy())

    def load_profile_data(self):
        """Populate fields from existing profile data"""
        data = self.profile_data

        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, data.get("name", ""))

        # Set the Odoo connection combo
        conn_name = data.get("odoo_connection_name", "")
        if conn_name and conn_name in self.odoo_conn_map:
            self.conn_combo.set(conn_name)

        self.source_dir_entry.delete(0, tk.END)
        self.source_dir_entry.insert(0, data.get("source_base_dir", ""))

        # Parse subdirs from JSON
        subdirs = data.get("source_subdirs", "[]")
        try:
            subdirs_list = json.loads(subdirs)
            self.subdirs_entry.delete(0, tk.END)
            self.subdirs_entry.insert(0, ",".join(subdirs_list))
        except (json.JSONDecodeError, TypeError):
            pass

        self.venv_entry.delete(0, tk.END)
        self.venv_entry.insert(0, data.get("venv_path", ""))

        # Parse extra files from JSON
        extra = data.get("extra_files", "[]")
        try:
            extra_list = json.loads(extra)
            self.extra_files_entry.delete(0, tk.END)
            self.extra_files_entry.insert(0, ",".join(extra_list))
        except (json.JSONDecodeError, TypeError):
            pass

        self.conf_path_entry.delete(0, tk.END)
        self.conf_path_entry.insert(0, data.get("odoo_conf_path", "odoo/odoo.conf"))

        self.container_dir_entry.delete(0, tk.END)
        self.container_dir_entry.insert(
            0, data.get("container_base_dir", "/opt/odoo/qlf")
        )

        self.pg_version_combo.set(data.get("postgres_version", "16"))
        self.py_version_combo.set(data.get("python_version", "3.12"))

        self.odoo_port_entry.delete(0, tk.END)
        self.odoo_port_entry.insert(0, str(data.get("odoo_port", 8069)))

        self.mailpit_port_entry.delete(0, tk.END)
        self.mailpit_port_entry.insert(0, str(data.get("mailpit_http_port", 8025)))

        custom_sql = data.get("custom_neutralize_sql", "")
        if custom_sql:
            self.custom_sql_text.insert("1.0", custom_sql)

    def validate_fields(self):
        """Validate required fields"""
        if not self.name_entry.get().strip():
            messagebox.showerror("Validation Error", "Profile name is required")
            self.name_entry.focus_set()
            return False

        if not self.conn_combo.get():
            messagebox.showerror(
                "Validation Error", "Please select an Odoo connection"
            )
            return False

        if not self.source_dir_entry.get().strip():
            messagebox.showerror(
                "Validation Error", "Source base directory is required"
            )
            self.source_dir_entry.focus_set()
            return False

        if not self.subdirs_entry.get().strip():
            messagebox.showerror(
                "Validation Error", "At least one subdirectory is required"
            )
            self.subdirs_entry.focus_set()
            return False

        try:
            int(self.odoo_port_entry.get())
            int(self.mailpit_port_entry.get())
        except ValueError:
            messagebox.showerror("Validation Error", "Ports must be numbers")
            return False

        return True

    def save_profile(self):
        """Save and close dialog"""
        if not self.validate_fields():
            return

        conn_name = self.conn_combo.get()
        odoo_conn_id = self.odoo_conn_map.get(conn_name)

        subdirs = [
            s.strip()
            for s in self.subdirs_entry.get().split(",")
            if s.strip()
        ]
        extra_files = [
            f.strip()
            for f in self.extra_files_entry.get().split(",")
            if f.strip()
        ]

        self.result = {
            "name": self.name_entry.get().strip(),
            "odoo_connection_id": odoo_conn_id,
            "source_base_dir": self.source_dir_entry.get().strip(),
            "source_subdirs": json.dumps(subdirs),
            "venv_path": self.venv_entry.get().strip(),
            "extra_files": json.dumps(extra_files),
            "odoo_conf_path": self.conf_path_entry.get().strip(),
            "container_base_dir": self.container_dir_entry.get().strip(),
            "postgres_version": self.pg_version_combo.get(),
            "python_version": self.py_version_combo.get(),
            "odoo_port": int(self.odoo_port_entry.get()),
            "mailpit_http_port": int(self.mailpit_port_entry.get()),
            "custom_neutralize_sql": self.custom_sql_text.get(
                "1.0", tk.END
            ).strip(),
        }

        self.destroy()
