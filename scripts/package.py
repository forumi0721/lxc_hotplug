#!/usr/bin/env python3
"""
Packaging utility for LXC USB Hotplug.
Creates clean, standalone distribution ZIP archives using Python's standard zipfile module.
Zero external dependencies.
"""

import os
import sys
import zipfile
import shutil

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(ROOT_DIR, "dist")


def add_file_to_zip(zf: zipfile.ZipFile, src_path: str, arc_path: str):
    """Adds a single file to the archive, preserving POSIX permissions (e.g. execute bit)."""
    if not os.path.exists(src_path):
        return

    st = os.stat(src_path)
    with open(src_path, "rb") as f:
        data = f.read()

    zinfo = zipfile.ZipInfo(arc_path)
    zinfo.date_time = (2026, 1, 1, 0, 0, 0)
    zinfo.compress_type = zipfile.ZIP_DEFLATED
    # Preserve permission bits (e.g. 0755 for scripts, 0644 for regular files)
    zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
    zf.writestr(zinfo, data)


def add_dir_to_zip(zf: zipfile.ZipFile, src_dir: str, arc_base: str):
    """Recursively adds directory contents to archive excluding __pycache__ and unwanted files."""
    for root, dirs, files in os.walk(src_dir):
        # Filter out __pycache__ and hidden files
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
        for file in sorted(files):
            if file.endswith((".pyc", ".pyo", ".pyd")) or file.startswith("."):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, src_dir)
            arc_path = os.path.join(arc_base, rel_path)
            add_file_to_zip(zf, full_path, arc_path)


def package_host(output_zip: str):
    """Packages Host Agent standalone distribution."""
    os.makedirs(os.path.dirname(output_zip), exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # Base scripts & entrypoints
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__init__.py"), "src/lxc_hotplug/__init__.py")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__main__.py"), "src/lxc_hotplug/__main__.py")

        # Common package
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "common"), "src/lxc_hotplug/common")

        # Host package
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "host"), "src/lxc_hotplug/host")

        # Config & Service
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "config", "host.yaml.example"), "config/host.yaml.example")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "systemd", "lxc-hotplug-host.service"), "systemd/lxc-hotplug-host.service")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "scripts", "install-host.sh"), "scripts/install-host.sh")

        # Docs
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "README.md"), "README.md")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "AGENTS.md"), "AGENTS.md")

    print(f"Created Host Agent distribution: {output_zip} ({os.path.getsize(output_zip)} bytes)")


def package_guest(output_zip: str):
    """Packages Guest Agent standalone distribution."""
    os.makedirs(os.path.dirname(output_zip), exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # Base scripts & entrypoints
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__init__.py"), "src/lxc_hotplug/__init__.py")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__main__.py"), "src/lxc_hotplug/__main__.py")

        # Common package
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "common"), "src/lxc_hotplug/common")

        # Guest package
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "src", "lxc_hotplug", "guest"), "src/lxc_hotplug/guest")

        # Config & Service
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "config", "guest.yaml.example"), "config/guest.yaml.example")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "systemd", "lxc-hotplug-guest.service"), "systemd/lxc-hotplug-guest.service")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "scripts", "install-guest.sh"), "scripts/install-guest.sh")

        # Docs
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "README.md"), "README.md")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "AGENTS.md"), "AGENTS.md")

    print(f"Created Guest Agent distribution: {output_zip} ({os.path.getsize(output_zip)} bytes)")


def package_all(output_zip: str):
    """Packages Complete distribution with all sources and tools."""
    os.makedirs(os.path.dirname(output_zip), exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "src"), "src")
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "config"), "config")
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "systemd"), "systemd")
        add_dir_to_zip(zf, os.path.join(ROOT_DIR, "scripts"), "scripts")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "Makefile"), "Makefile")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "README.md"), "README.md")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "AGENTS.md"), "AGENTS.md")
        add_file_to_zip(zf, os.path.join(ROOT_DIR, "TECH_ANALYSIS.md"), "TECH_ANALYSIS.md")

    print(f"Created Complete distribution: {output_zip} ({os.path.getsize(output_zip)} bytes)")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "dist"
    host_zip = os.path.join(DIST_DIR, "lxc-hotplug-host.zip")
    guest_zip = os.path.join(DIST_DIR, "lxc-hotplug-guest.zip")
    all_zip = os.path.join(DIST_DIR, "lxc-hotplug-all.zip")

    if target == "host":
        package_host(host_zip)
    elif target == "guest":
        package_guest(guest_zip)
    elif target == "all":
        package_all(all_zip)
    elif target == "dist":
        package_host(host_zip)
        package_guest(guest_zip)
        package_all(all_zip)
    else:
        print(f"Unknown target: {target}. Available: host, guest, all, dist")
        sys.exit(1)


if __name__ == "__main__":
    main()
