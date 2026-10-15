.PHONY: all help test zip host-zip guest-zip all-zip deb arch alpine dist clean

PYTHON ?= python3
PYTHONPATH_VAR = src

all: test dist

help:
	@echo "LXC USB Hotplug Multi-Distribution Packaging System"
	@echo "====================================================="
	@echo "Available make targets:"
	@echo "  make test       - Run all unit tests"
	@echo "  make zip        - Build all standalone ZIP distribution packages"
	@echo "  make host-zip   - Build Host Agent ZIP (dist/lxc-hotplug-host.zip)"
	@echo "  make guest-zip  - Build Guest Agent ZIP (dist/lxc-hotplug-guest.zip)"
	@echo "  make deb        - Build Debian / Ubuntu (.deb) packages for Host & Guest"
	@echo "  make arch       - Build Arch Linux (.pkg.tar.zst) packages for Host & Guest"
	@echo "  make alpine     - Build Alpine Linux (OpenRC bundle) packages for Host & Guest"
	@echo "  make dist       - Build ALL distribution formats (ZIP, DEB, ARCH, ALPINE) in dist/"
	@echo "  make clean      - Remove build artifacts, packages, and __pycache__"

test:
	@echo "Running test suite..."
	@PYTHONPATH=$(PYTHONPATH_VAR) $(PYTHON) -m unittest discover -s tests -p "test_*.py"

# ZIP distributions
host-zip:
	@echo "Packaging Host Agent ZIP..."
	@$(PYTHON) scripts/package.py host

guest-zip:
	@echo "Packaging Guest Agent ZIP..."
	@$(PYTHON) scripts/package.py guest

all-zip:
	@echo "Packaging All-in-one ZIP..."
	@$(PYTHON) scripts/package.py all

zip: host-zip guest-zip all-zip

# Native Linux packages
deb:
	@echo "Building Debian (.deb) packages..."
	@$(PYTHON) scripts/build-packages.py deb

arch:
	@echo "Building Arch Linux (.pkg.tar.zst) packages..."
	@$(PYTHON) scripts/build-packages.py arch

alpine:
	@echo "Building Alpine Linux packages..."
	@$(PYTHON) scripts/build-packages.py alpine

# Full distribution build
dist: zip deb arch alpine
	@echo ""
	@echo "=== All distributions successfully built in dist/ ==="
	@ls -lh dist/*.zip dist/*.deb dist/*.pkg.tar.zst dist/*alpine.tar.gz

clean:
	@echo "Cleaning up build artifacts and cache..."
	@rm -rf dist build
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Clean complete."
