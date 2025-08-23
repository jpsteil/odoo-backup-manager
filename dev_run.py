#!/usr/bin/env python3
"""
Development runner - Use this to test without installing
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Now import and run the CLI
from odoo_backup_tool.cli import main

if __name__ == "__main__":
    main()