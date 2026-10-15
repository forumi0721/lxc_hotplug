#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing LXC USB Hotplug Host Agent ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="/opt/lxc_hotplug"
CONFIG_DIR="/etc/lxc-hotplug"
SOCKET_DIR="/run/lxc-hotplug"

# 1. Deploy files to /opt/lxc_hotplug if executed from another folder
if [[ "${SOURCE_DIR}" != "${INSTALL_DIR}" ]]; then
    echo "Deploying files from ${SOURCE_DIR} to ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}"
    cp -r "${SOURCE_DIR}/src" "${INSTALL_DIR}/"
    cp -r "${SOURCE_DIR}/config" "${INSTALL_DIR}/"
    cp -r "${SOURCE_DIR}/systemd" "${INSTALL_DIR}/"
    cp -r "${SOURCE_DIR}/scripts" "${INSTALL_DIR}/"
fi

# 2. Ensure directories and permissions
mkdir -p "${CONFIG_DIR}"
mkdir -p "${SOCKET_DIR}"
chmod 755 "${SOCKET_DIR}"

# 3. Setup default configuration
if [[ ! -f "${CONFIG_DIR}/host.yaml" ]]; then
    echo "Copying default host.yaml to ${CONFIG_DIR}/host.yaml..."
    cp "${INSTALL_DIR}/config/host.yaml.example" "${CONFIG_DIR}/host.yaml"
fi

# 4. Install and enable systemd service
echo "Installing systemd service unit..."
cp "${INSTALL_DIR}/systemd/lxc-hotplug-host.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lxc-hotplug-host.service

echo ""
echo "=== Installation complete! ==="
echo "Please edit ${CONFIG_DIR}/host.yaml to specify target container VMIDs, then start the service:"
echo "  sudo systemctl start lxc-hotplug-host.service"
echo "  sudo journalctl -u lxc-hotplug-host.service -f"
