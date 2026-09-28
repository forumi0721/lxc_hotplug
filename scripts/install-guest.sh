#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing LXC USB Hotplug Guest Agent ==="

INSTALL_DIR="/opt/lxc_hotplug"
CONFIG_DIR="/etc/lxc-hotplug"
HOOKS_DIR="/etc/lxc-hotplug/hooks.d"

mkdir -p "${CONFIG_DIR}"
mkdir -p "${HOOKS_DIR}"

if [[ ! -f "${CONFIG_DIR}/guest.yaml" ]]; then
    echo "Copying default guest.yaml to ${CONFIG_DIR}/guest.yaml..."
    cp "${INSTALL_DIR}/config/guest.yaml.example" "${CONFIG_DIR}/guest.yaml"
fi

if [[ ! -f "${HOOKS_DIR}/on-change.sh" ]]; then
    echo "Creating sample hook script at ${HOOKS_DIR}/on-change.sh..."
    cat << 'EOF' > "${HOOKS_DIR}/on-change.sh"
#!/usr/bin/env bash
# Sample hook script called when USB devices settle
logger -t lxc-hotplug "USB devices settled and synchronized."
EOF
    chmod +x "${HOOKS_DIR}/on-change.sh"
fi

echo "Installing systemd service unit..."
cp "${INSTALL_DIR}/systemd/lxc-hotplug-guest.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable lxc-hotplug-guest.service

echo "Installation complete!"
echo "Please edit ${CONFIG_DIR}/guest.yaml with your filter rules, then run:"
echo "  systemctl start lxc-hotplug-guest.service"
