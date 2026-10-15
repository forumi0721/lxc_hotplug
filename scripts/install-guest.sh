#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing LXC USB Hotplug Guest Agent ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="/opt/lxc_hotplug"
CONFIG_DIR="/etc/lxc-hotplug"
HOOKS_DIR="/etc/lxc-hotplug/hooks.d"

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
mkdir -p "${HOOKS_DIR}"

# 3. Setup default configuration
if [[ ! -f "${CONFIG_DIR}/guest.yaml" ]]; then
    echo "Copying default guest.yaml to ${CONFIG_DIR}/guest.yaml..."
    cp "${INSTALL_DIR}/config/guest.yaml.example" "${CONFIG_DIR}/guest.yaml"
fi

# 4. Create sample hook script if missing
if [[ ! -f "${HOOKS_DIR}/on-change.sh" ]]; then
    echo "Creating sample hook script at ${HOOKS_DIR}/on-change.sh..."
    cat << 'EOF' > "${HOOKS_DIR}/on-change.sh"
#!/usr/bin/env bash
# Sample hook script called when USB devices settle
logger -t lxc-hotplug "USB devices settled and synchronized."
EOF
    chmod +x "${HOOKS_DIR}/on-change.sh"
fi

# 5. Install and enable systemd service
echo "Installing systemd service unit..."
cp "${INSTALL_DIR}/systemd/lxc-hotplug-guest.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lxc-hotplug-guest.service

echo ""
echo "=== Installation complete! ==="
echo "Please edit ${CONFIG_DIR}/guest.yaml with your filter rules and VMID, then start the service:"
echo "  sudo systemctl start lxc-hotplug-guest.service"
echo "  sudo journalctl -u lxc-hotplug-guest.service -f"
