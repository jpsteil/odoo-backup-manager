"""
Setup script for Odoo Backup Tool
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text() if (this_directory / "README.md").exists() else ""

setup(
    name="odoo-backup-manager",
    version="1.1.0",
    author="Jim Steil",
    description="A comprehensive backup and restore utility for Odoo instances",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jpsteil/odoo-backup-manager",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Archiving :: Backup",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "cryptography>=41.0.0",
        "paramiko>=3.0.0",
    ],
    extras_require={
        "gui": ["tkinter"],  # Note: tkinter usually comes with Python
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "odoo-backup=odoo_backup_tool.cli:main",
            "odoo-backup-gui=odoo_backup_tool.gui_launcher:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)