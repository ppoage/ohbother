-include .env

# Ensure Poetry creates the virtual environment in the project directory.
export POETRY_VIRTUALENVS_IN_PROJECT = true

# Directories
SOURCE_DIR = src
TEST_DIR = tests
PROJECT_DIRS = $(SOURCE_DIR) $(TEST_DIR)
PWD := $(dir $(abspath $(firstword $(MAKEFILE_LIST))))

# Project Variables
PROJECT_VERSION ?= v$(shell poetry version -s)
PROJECT_NAME ?= my_project
PYTHON_VERSION ?= 3.11
# Default Python command (override with PYTHON_CMD=python3.11 if needed)
PYTHON_CMD ?= python

.DEFAULT_GOAL := all

.PHONY: install-poetry init-env init format lint audit test build build-poetry wheel info clean all

# Target to install Poetry if not already installed
install-poetry:
	@command -v poetry >/dev/null 2>&1 || { \
	    echo "Poetry not found. Installing Poetry..."; \
	    curl -sSL https://install.python-poetry.org | $(PYTHON_CMD); \
	    echo "Please ensure $$HOME/.local/bin is in your PATH"; \
	}

# Initialize environment variables file.
init-env:
	@echo "Initializing environment..."
	@$(PYTHON_CMD) -c "open('.env', 'a').close()"
	@echo "PROJECT_NAME=$(PROJECT_NAME)" >> .env
	@echo "PYTHON_VERSION=$(PYTHON_VERSION)" >> .env

# Initialize environment: install Poetry and then dependencies.
init: install-poetry init-env
	@echo "Installing dependencies via Poetry..."
	poetry install

# Check the pyproject.toml for issues.
-check-toml:
	@echo "Checking pyproject.toml..."
	poetry check

# Reformat source and test directories.
-reformat-src:
	@echo "Formatting source code..."
	poetry run black $(PROJECT_DIRS)
	@echo "Sorting imports..."
	poetry run isort $(PROJECT_DIRS)

format: -check-toml -reformat-src

# Run linting tools.
-lint-src:
	@echo "Linting source code..."
	poetry run ruff check $(SOURCE_DIR)
	@echo "Running mypy type checks..."
	poetry run mypy --install-types --show-error-codes --non-interactive $(SOURCE_DIR)

lint: -lint-src

# Audit the source code.
audit:
	@echo "Running security audit..."
	poetry run bandit -r $(SOURCE_DIR) -x $(TEST_DIR)

# Run tests.
test:
	@echo "Running tests..."
	poetry run pytest $(TEST_DIR)

# Build the library using build.py in dev mode.
build:
	@echo "Building library (dev mode)..."
	$(PYTHON_CMD) build.py --dev

# Build the Poetry wheel via build.py with the --poetry flag.
build-poetry:
	@echo "Building Poetry wheel..."
	$(PYTHON_CMD) build.py --poetry

# Optionally, provide a target alias for wheel.
wheel: build-poetry
	@echo "Wheel built in the 'dist' directory."

# Default target: run formatting, linting, audit, tests, and both build steps.
all: format lint audit test build build-poetry

info:
	@echo "Project name: $(PROJECT_NAME)"
	@echo "Project version: $(PROJECT_VERSION)"
	@echo "Python version: $(PYTHON_VERSION)"

# Clean generated files.
clean:
	@echo "Cleaning up generated files..."
	rm -rf .env dist build