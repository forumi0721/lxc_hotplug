#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing LXC USB Hotplug Host Agent ==="

INSTALL_DIR="/opt/lxc_hotplug"
CONFIG_DIR="/etc/lxc-hotplug"
SOCKET_DIR="/run/lxc-hotplug"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${SOCKET_DIR}"
chmod 755 "${SOCKET_DIR}"

if [[ ! -f "${CONFIG_DIR}/host.yaml" ]]; then
    echo "Copying default host.yaml to ${CONFIG_DIR}/host.yaml..."
    cp "${INSTALL_DIR}/config/host.yaml.example" "${CONFIG_DIR}/host.yaml"
fi

echo "Installing systemd service unit..."
cp "${INSTALL_DIR}/systemd/lxc-hotplug-host.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lxc-hotplug-host.service

echo "Installation complete!"
echo "Please edit ${CONFIG_DIR}/host.yaml to specify your container VMIDs, then run:"
echo "  systemctl start lxc-hotplug-host.service"
