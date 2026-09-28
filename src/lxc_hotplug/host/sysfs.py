"""
sysfs USB device metadata resolver.
Traverses the sysfs directory hierarchy to locate USB attributes (VID, PID, Serial, Product).
"""

import os
import time
from typing import Dict, Optional, Tuple


def _read_sysfs_attr(dir_path: str, attr_name: str) -> Optional[str]:
    """Safely reads a sysfs attribute file."""
    attr_path = os.path.join(dir_path, attr_name)
    try:
        if os.path.isfile(attr_path):
            with open(attr_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
    except OSError:
        pass
    return None


def resolve_usb_metadata(devpath: str, max_retries: int = 3, retry_delay: float = 0.05) -> Dict[str, Optional[str]]:
    """
    Extracts USB device properties (vendor_id, product_id, vendor, product, serial)
    by inspecting /sys<DEVPATH> and traversing parent directories.
    Retries up to max_retries to handle race conditions during device enumeration.
    """
    sys_base = "/sys"
    target_dir = os.path.join(sys_base, devpath.lstrip("/"))

    metadata = {
        "vendor_id": None,
        "product_id": None,
        "vendor": None,
        "product": None,
        "serial": None
    }

    for attempt in range(max_retries):
        cur = target_dir
        # Traverse upwards until reaching /sys/devices or root
        while cur and cur != sys_base and cur != os.path.dirname(cur):
            # Check for standard USB sysfs attributes
            v_id = _read_sysfs_attr(cur, "idVendor")
            p_id = _read_sysfs_attr(cur, "idProduct")

            if v_id and p_id:
                metadata["vendor_id"] = v_id.lower()
                metadata["product_id"] = p_id.lower()
                metadata["vendor"] = _read_sysfs_attr(cur, "manufacturer")
                metadata["product"] = _read_sysfs_attr(cur, "product")
                metadata["serial"] = _read_sysfs_attr(cur, "serial")
                return metadata

            cur = os.path.dirname(cur)

        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    return metadata
