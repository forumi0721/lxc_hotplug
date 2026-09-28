"""
cgroup v2 and dynamic device permission manager for Host Agent.
Handles Tiered resolution for unknown major devices.
"""

import logging
import subprocess
from typing import Set, Dict, Any, Optional

DEFAULT_KNOWN_MAJORS = {
    188,  # ttyUSB
    166,  # ttyACM
    116,  # sound
    243,  # hidraw
    240,  # hiddev (common)
}


class CgroupManager:
    """
    Manages container device access permissions under cgroup v2.
    """
    def __init__(self, known_majors: Optional[Set[int]] = None, dynamic_inject: bool = True, logger: Optional[logging.Logger] = None):
        self.known_majors: Set[int] = set(known_majors) if known_majors else set(DEFAULT_KNOWN_MAJORS)
        self.dynamic_inject = dynamic_inject
        self.logger = logger or logging.getLogger("CgroupManager")

    def ensure_device_access(self, vmid: int, devname: str, major: int, minor: int) -> bool:
        """
        Ensures the container has cgroup permission to access the device.
        Returns True if access is guaranteed/injected, or False if denied.
        """
        # Tier 1: Known major numbers (or when container config has c *:* rwm)
        if major in self.known_majors:
            return True

        self.logger.warning(
            f"[VMID {vmid}] Unknown major number {major}:{minor} detected for /dev/{devname}."
        )

        # Tier 2: Dynamic injection using lxc-device add
        if self.dynamic_inject:
            dev_path = f"/dev/{devname}"
            self.logger.info(f"[VMID {vmid}] Attempting dynamic cgroup injection: lxc-device add {dev_path}")
            try:
                cmd = ["lxc-device", "-n", str(vmid), "add", dev_path]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                if res.returncode == 0:
                    self.logger.info(f"[VMID {vmid}] Successfully injected cgroup permission for {dev_path}")
                    # Cache this major for future events
                    self.known_majors.add(major)
                    return True
                else:
                    self.logger.error(
                        f"[VMID {vmid}] lxc-device add failed (code {res.returncode}): {res.stderr.strip()}"
                    )
            except Exception as e:
                self.logger.error(f"[VMID {vmid}] Dynamic injection error: {e}")

        # Tier 3: Injection not enabled or failed
        self.logger.warning(f"[VMID {vmid}] Device /dev/{devname} (major {major}) may not be accessible in guest.")
        return False
