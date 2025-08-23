# Makefile for Odoo Backup Tool Development

.PHONY: all help install build test check clean distclean run run-cli run-gui lint format deps dev

# Default target - typically builds/compiles the project
all: install

# Standard help target
help:
	@echo "Standard targets:"
	@echo "  make all        - Default target (same as install)"
	@echo "  make install    - Install the package"
	@echo "  make build      - Build distribution packages"
	@echo "  make test       - Run test suite"
	@echo "  make check      - Run all checks (lint + test)"
	@echo "  make clean      - Remove generated files"
	@echo "  make distclean  - Remove everything including venv"
	@echo ""
	@echo "Development targets:"
	@echo "  make dev        - Set up development environment"
	@echo "  make deps       - Install dependencies only"
	@echo "  make run        - Run the main program (GUI)"
	@echo "  make run-cli    - Run CLI interface"
	@echo "  make run-gui    - Run GUI interface"
	@echo "  make lint       - Check code style"
	@echo "  make format     - Auto-format code"

# Install dependencies only
deps:
	@if [ ! -d "venv" ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv venv; \
	fi
	@echo "Installing dependencies..."
	@venv/bin/pip install --upgrade pip -q
	@venv/bin/pip install -r requirements.txt -q
	@echo "Dependencies installed!"

# Set up development environment
dev: deps
	@echo "Installing development dependencies..."
	@venv/bin/pip install -r requirements-dev.txt -q
	@echo "Development environment ready!"

# Install package (standard target)
install: deps
	@echo "Installing package..."
	@venv/bin/pip install -e . -q
	@echo "Package installed!"

# Build distribution packages (standard target)
build: dev
	@echo "Building distribution packages..."
	@venv/bin/pip install --upgrade build -q
	@venv/bin/python -m build
	@echo "Build complete! Check dist/ directory"

# Run the default program (standard target)
run: run-gui

# Run CLI without installation
run-cli:
	@./dev_run.sh $(ARGS)

# Run GUI without installation  
run-gui:
	@PYTHONPATH=. venv/bin/python -m odoo_backup_tool.gui_launcher

# Run tests (standard target)
test: dev
	@echo "Running tests..."
	@PYTHONPATH=. venv/bin/python test_import.py
	@if [ -d "tests" ]; then \
		PYTHONPATH=. venv/bin/pytest tests/; \
	else \
		echo "No tests directory found"; \
	fi

# Run all checks - lint and test (standard target)
check: lint test
	@echo "All checks passed!"

# Lint code
lint: dev
	@echo "Running flake8..."
	@venv/bin/flake8 odoo_backup_tool/ --max-line-length=100 --ignore=E203,W503

# Format code
format: dev
	@echo "Formatting code with black..."
	@venv/bin/black odoo_backup_tool/

# Clean up generated files (standard target)
clean:
	@echo "Cleaning up generated files..."
	@rm -rf build/ dist/ *.egg-info
	@rm -rf __pycache__ */__pycache__ */*/__pycache__
	@rm -rf .pytest_cache .coverage htmlcov/
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@find . -type f -name "*~" -delete
	@find . -type f -name ".DS_Store" -delete
	@echo "Clean complete!"

# Deep clean - remove everything including venv (standard target)
distclean: clean
	@echo "Removing virtual environment..."
	@rm -rf venv/
	@echo "Distclean complete!"

# Show usage examples
examples:
	@echo "Examples:"
	@echo "  make              # Install package"
	@echo "  make test         # Run tests"
	@echo "  make check        # Run all checks"
	@echo "  make build        # Create distribution packages"
	@echo "  make run          # Launch GUI"
	@echo "  make run-cli ARGS='--help'"
	@echo "  make run-cli ARGS='backup --name mydb --host localhost --user odoo'"
	@echo "  make run-cli ARGS='connections list'"