.PHONY: all help test host-zip guest-zip all-zip dist clean

PYTHON ?= python3
PYTHONPATH_VAR = src

all: test dist

help:
	@echo "LXC USB Hotplug Build & Packaging System"
	@echo "========================================="
	@echo "Available make targets:"
	@echo "  make test       - Run all unit tests"
	@echo "  make host-zip   - Build Host Agent distribution package (dist/lxc-hotplug-host.zip)"
	@echo "  make guest-zip  - Build Guest Agent distribution package (dist/lxc-hotplug-guest.zip)"
	@echo "  make all-zip    - Build Full combined package (dist/lxc-hotplug-all.zip)"
	@echo "  make dist       - Build all ZIP distribution packages in dist/"
	@echo "  make clean      - Remove build artifacts, ZIPs, and __pycache__"

test:
	@echo "Running test suite..."
	@PYTHONPATH=$(PYTHONPATH_VAR) $(PYTHON) -m unittest discover -s tests -p "test_*.py"

host-zip:
	@echo "Packaging Host Agent ZIP..."
	@$(PYTHON) scripts/package.py host

guest-zip:
	@echo "Packaging Guest Agent ZIP..."
	@$(PYTHON) scripts/package.py guest

all-zip:
	@echo "Packaging All-in-one ZIP..."
	@$(PYTHON) scripts/package.py all

dist:
	@echo "Building all distribution packages..."
	@$(PYTHON) scripts/package.py dist
	@echo "Distributions built in dist/:"
	@ls -lh dist/

clean:
	@echo "Cleaning up build artifacts and cache..."
	@rm -rf dist build
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Clean complete."
