#!/bin/bash
# Development runner script - runs without installation

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Add project to PYTHONPATH
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

# Check if virtual environment exists
if [ ! -d "${SCRIPT_DIR}/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "${SCRIPT_DIR}/venv"
    echo "Installing dependencies..."
    "${SCRIPT_DIR}/venv/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" --quiet
fi

# Activate virtual environment and run
"${SCRIPT_DIR}/venv/bin/python" -m odoo_backup_tool.cli "$@"