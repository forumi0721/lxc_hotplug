#!/usr/bin/env python3
"""
Multi-distribution packaging builder for LXC USB Hotplug.
Builds native packages:
  - Debian (.deb) via dpkg-deb
  - Arch Linux (.pkg.tar.zst) via tar + zstd
  - Alpine Linux (.tar.gz bundle with OpenRC + APKBUILD)
"""

import os
import sys
import stat
import time
import shutil
import subprocess

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(ROOT_DIR, "dist")
VERSION = "1.0.0"


def copy_python_sources(target_opt_dir: str, role: str):
    """Copies common and role-specific python sources into /opt/lxc_hotplug."""
    src_dest = os.path.join(target_opt_dir, "src", "lxc_hotplug")
    os.makedirs(src_dest, exist_ok=True)

    # Core files
    shutil.copy2(os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__init__.py"), src_dest)
    shutil.copy2(os.path.join(ROOT_DIR, "src", "lxc_hotplug", "__main__.py"), src_dest)

    # Common package
    shutil.copytree(
        os.path.join(ROOT_DIR, "src", "lxc_hotplug", "common"),
        os.path.join(src_dest, "common"),
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )

    # Role package (host or guest)
    shutil.copytree(
        os.path.join(ROOT_DIR, "src", "lxc_hotplug", role),
        os.path.join(src_dest, role),
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )

    # Config example & scripts
    cfg_dest = os.path.join(target_opt_dir, "config")
    os.makedirs(cfg_dest, exist_ok=True)
    shutil.copy2(os.path.join(ROOT_DIR, "config", f"{role}.yaml.example"), cfg_dest)


# ==============================================================================
# 1. Debian (.deb) Packaging
# ==============================================================================
def build_deb(role: str):
    pkg_name = f"lxc-hotplug-{role}"
    staging_dir = os.path.join(DIST_DIR, "staging", "deb", pkg_name)
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # 1. Copy payload to /opt/lxc_hotplug
    opt_dir = os.path.join(staging_dir, "opt", "lxc_hotplug")
    copy_python_sources(opt_dir, role)

    # 2. Systemd service to /lib/systemd/system/
    systemd_dir = os.path.join(staging_dir, "lib", "systemd", "system")
    os.makedirs(systemd_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(ROOT_DIR, "systemd", f"{pkg_name}.service"),
        os.path.join(systemd_dir, f"{pkg_name}.service")
    )

    # 3. Control files
    debian_src = os.path.join(ROOT_DIR, "packaging", "debian", role, "DEBIAN")
    debian_dst = os.path.join(staging_dir, "DEBIAN")
    shutil.copytree(debian_src, debian_dst)

    # Ensure scripts are executable
    for script_name in ["postinst", "prerm"]:
        p = os.path.join(debian_dst, script_name)
        if os.path.exists(p):
            os.chmod(p, 0o755)

    # 4. Build .deb using dpkg-deb
    output_deb = os.path.join(DIST_DIR, f"{pkg_name}_{VERSION}_all.deb")
    cmd = ["dpkg-deb", "--build", "--root-owner-group", staging_dir, output_deb]
    subprocess.run(cmd, check=True)
    print(f"[DEB] Built {output_deb} ({os.path.getsize(output_deb)} bytes)")


# ==============================================================================
# 2. Arch Linux (.pkg.tar.zst) Packaging
# ==============================================================================
def build_arch(role: str):
    pkg_name = f"lxc-hotplug-{role}"
    staging_dir = os.path.join(DIST_DIR, "staging", "arch", pkg_name)
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # 1. Payload to /opt/lxc_hotplug
    opt_dir = os.path.join(staging_dir, "opt", "lxc_hotplug")
    copy_python_sources(opt_dir, role)

    # 2. Config to /etc/lxc-hotplug/
    etc_dir = os.path.join(staging_dir, "etc", "lxc-hotplug")
    os.makedirs(etc_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(ROOT_DIR, "config", f"{role}.yaml.example"),
        os.path.join(etc_dir, f"{role}.yaml")
    )

    # 3. Systemd service to /usr/lib/systemd/system/
    systemd_dir = os.path.join(staging_dir, "usr", "lib", "systemd", "system")
    os.makedirs(systemd_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(ROOT_DIR, "systemd", f"{pkg_name}.service"),
        os.path.join(systemd_dir, f"{pkg_name}.service")
    )

    # 4. Calculate installed size
    total_size = sum(
        os.path.getsize(os.path.join(dirpath, filename))
        for dirpath, dirnames, filenames in os.walk(staging_dir)
        for filename in filenames
    )

    # 5. Generate .PKGINFO
    pkginfo_content = f"""pkgname = {pkg_name}
pkgver = {VERSION}-1
pkgdesc = LXC USB Hotplug {role.capitalize()} Agent for Arch Linux
url = https://github.com/forumi0721/lxc_hotplug
builddate = {int(time.time())}
packager = LXC Hotplug Team
size = {total_size}
arch = any
license = MIT
depend = python
backup = etc/lxc-hotplug/{role}.yaml
"""
    with open(os.path.join(staging_dir, ".PKGINFO"), "w", encoding="utf-8") as f:
        f.write(pkginfo_content)

    # Copy install scriptlet as .INSTALL
    install_src = os.path.join(ROOT_DIR, "packaging", "arch", role, f"{pkg_name}.install")
    if os.path.exists(install_src):
        shutil.copy2(install_src, os.path.join(staging_dir, ".INSTALL"))

    # 6. Compress with tar + zstd
    output_pkg = os.path.join(DIST_DIR, f"{pkg_name}-{VERSION}-1-any.pkg.tar.zst")
    if os.path.exists(output_pkg):
        os.unlink(output_pkg)
    # Run tar pipe into zstd (-f to force overwrite)
    tar_cmd = f"tar -C '{staging_dir}' --owner=0 --group=0 -cf - . | zstd -T0 -19 -f -o '{output_pkg}'"
    subprocess.run(tar_cmd, shell=True, check=True)
    print(f"[ARCH] Built {output_pkg} ({os.path.getsize(output_pkg)} bytes)")


# ==============================================================================
# 3. Alpine Linux (OpenRC Bundle & APK Package)
# ==============================================================================
def build_alpine(role: str):
    pkg_name = f"lxc-hotplug-{role}"
    staging_dir = os.path.join(DIST_DIR, "staging", "alpine", pkg_name)
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # 1. Payload to /opt/lxc_hotplug
    opt_dir = os.path.join(staging_dir, "opt", "lxc_hotplug")
    copy_python_sources(opt_dir, role)

    # 2. Config to /etc/lxc-hotplug/
    etc_dir = os.path.join(staging_dir, "etc", "lxc-hotplug")
    os.makedirs(etc_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(ROOT_DIR, "config", f"{role}.yaml.example"),
        os.path.join(etc_dir, f"{role}.yaml")
    )

    # 3. OpenRC service to /etc/init.d/
    initd_dir = os.path.join(staging_dir, "etc", "init.d")
    os.makedirs(initd_dir, exist_ok=True)
    initd_dest = os.path.join(initd_dir, pkg_name)
    shutil.copy2(
        os.path.join(ROOT_DIR, "packaging", "alpine", role, f"{pkg_name}.initd"),
        initd_dest
    )
    os.chmod(initd_dest, 0o755)

    # 4. Standalone install script for Alpine
    installer_path = os.path.join(staging_dir, "install-alpine.sh")
    with open(installer_path, "w", encoding="utf-8") as f:
        f.write(f"""#!/bin/sh
set -e
echo "=== Installing {pkg_name} on Alpine Linux ==="
apk add --no-cache python3
mkdir -p /opt/lxc_hotplug /etc/lxc-hotplug /etc/init.d
cp -r opt/lxc_hotplug/* /opt/lxc_hotplug/
if [ ! -f /etc/lxc-hotplug/{role}.yaml ]; then
    cp etc/lxc-hotplug/{role}.yaml /etc/lxc-hotplug/
fi
cp etc/init.d/{pkg_name} /etc/init.d/
chmod 755 /etc/init.d/{pkg_name}
rc-update add {pkg_name} default
echo "Installation complete! Start service via: rc-service {pkg_name} start"
""")
    os.chmod(installer_path, 0o755)

    # 5. Compress into tar.gz
    output_tar = os.path.join(DIST_DIR, f"{pkg_name}-{VERSION}-alpine.tar.gz")
    tar_cmd = f"tar -C '{staging_dir}' --owner=0 --group=0 -czf '{output_tar}' ."
    subprocess.run(tar_cmd, shell=True, check=True)
    print(f"[ALPINE] Built {output_tar} ({os.path.getsize(output_tar)} bytes)")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(DIST_DIR, exist_ok=True)

    if target in ("deb", "debian"):
        build_deb("host")
        build_deb("guest")
    elif target in ("arch", "pacman"):
        build_arch("host")
        build_arch("guest")
    elif target in ("alpine", "apk"):
        build_alpine("host")
        build_alpine("guest")
    elif target in ("all", "pkgs"):
        build_deb("host")
        build_deb("guest")
        build_arch("host")
        build_arch("guest")
        build_alpine("host")
        build_alpine("guest")
    else:
        print(f"Unknown target: {target}. Available: deb, arch, alpine, all")
        sys.exit(1)


if __name__ == "__main__":
    main()
