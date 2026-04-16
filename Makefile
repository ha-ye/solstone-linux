# solstone-linux Makefile
# Standalone Linux desktop observer for solstone

.PHONY: install test test-only format ci clean clean-install versions all deploy upgrade service-restart service-status service-logs uninstall-service

# Default target
all: install

# Virtual environment directory
VENV := .venv
VENV_BIN := $(VENV)/bin
PYTHON := $(VENV_BIN)/python

# Require uv
UV := $(shell command -v uv 2>/dev/null)
ifndef UV
$(error uv is not installed. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh)
endif

APP := solstone-linux
UNIT := solstone-linux.service
PIPX_FLAGS := --system-site-packages

# Marker file to track installation
.installed: pyproject.toml
	@echo "Installing package with uv (including dev tools)..."
	$(UV) sync --group dev
	@touch .installed

# Install package in editable mode with isolated venv
install: .installed

deploy:
	@command -v pipx >/dev/null || { echo "pipx not found — install with: sudo dnf install pipx (or apt/brew equivalent)"; exit 1; }
	# Editable installs (pipx install -e .) are deliberately avoided: pipx treats editable installs differently and system-site-packages behavior is unreliable with them.
	pipx install --force $(PIPX_FLAGS) .
	$(APP) install-service
	systemctl --user --no-pager status $(UNIT) | head

upgrade: ci
	pipx install --force $(PIPX_FLAGS) .
	systemctl --user daemon-reload
	systemctl --user restart $(UNIT)
	systemctl --user --no-pager status $(UNIT) | head

service-restart:
	systemctl --user restart $(UNIT)

service-status:
	systemctl --user --no-pager status $(UNIT)

service-logs:
	journalctl --user -u $(UNIT) -n 100 --no-pager -f

uninstall-service:
	-systemctl --user disable --now $(UNIT)
	-rm -f $$HOME/.config/systemd/user/$(UNIT)
	-systemctl --user daemon-reload
	-pipx uninstall $(APP)

# Venv tool shortcuts
PYTEST := $(VENV_BIN)/pytest
RUFF := $(VENV_BIN)/ruff

# Run all tests
test: .installed
	@echo "Running tests..."
	$(PYTEST) tests/ -q

# Run specific test file or pattern
test-only: .installed
	@if [ -z "$(TEST)" ]; then \
		echo "Usage: make test-only TEST=<test_file_or_pattern>"; \
		echo "Example: make test-only TEST=tests/test_config.py"; \
		echo "Example: make test-only TEST=\"-k test_function_name\""; \
		exit 1; \
	fi
	$(PYTEST) $(TEST)

# Auto-format and fix code, then report remaining issues
format: .installed
	@echo "Formatting and fixing code with ruff..."
	@$(RUFF) format .
	@$(RUFF) check --fix .
	@echo ""
	@echo "Checking for remaining issues..."
	@$(RUFF) check . || { echo ""; echo "Issues above need manual fixes."; exit 1; }
	@echo ""
	@echo "All clean!"

# Run CI checks (what CI would run)
ci: .installed
	@echo "Running CI checks..."
	@echo "=== Checking formatting ==="
	@$(RUFF) format --check . || { echo "Run 'make format' to fix formatting"; exit 1; }
	@echo ""
	@echo "=== Running ruff ==="
	@$(RUFF) check . || { echo "Run 'make format' to auto-fix"; exit 1; }
	@echo ""
	@echo "=== Running tests ==="
	@$(MAKE) test
	@echo ""
	@echo "All CI checks passed!"

# Clean build artifacts and cache files
clean:
	@echo "Cleaning build artifacts and cache files..."
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .mypy_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -f .installed

# Clean everything and reinstall
clean-install: clean install

# Show installed package versions
versions: .installed
	@echo "=== Python version ==="
	$(PYTHON) --version
	@echo ""
	@echo "=== Installed packages ==="
	@$(UV) pip list | grep -E "^(pytest|ruff|requests|numpy|soundfile|soundcard|dbus-next|PyGObject)" || true
