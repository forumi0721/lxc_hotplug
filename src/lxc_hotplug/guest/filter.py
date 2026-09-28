"""
Guest Agent Device Filter Engine.
Evaluates incoming device metadata against rules defined in guest.yaml.
"""

import fnmatch
from typing import Dict, Any, List, Optional


class FilterRule:
    """Represents a single filter rule for matching a device."""
    def __init__(self, rule_dict: Dict[str, Any]):
        self.subsystem: Optional[str] = rule_dict.get("subsystem")
        self.vendor_id: Optional[str] = rule_dict.get("vendor_id", "").lower() if rule_dict.get("vendor_id") else None
        self.product_id: Optional[str] = rule_dict.get("product_id", "").lower() if rule_dict.get("product_id") else None
        self.serial: Optional[str] = rule_dict.get("serial")
        # devname_pattern can be pipe-separated e.g. "ttyACM*|ttyUSB*"
        pattern_str = rule_dict.get("devname_pattern")
        self.devname_patterns: List[str] = [p.strip() for p in pattern_str.split("|")] if pattern_str else []

    def matches(self, device: Dict[str, Any]) -> bool:
        """Checks if a device satisfies all constraints in this rule."""
        if self.subsystem and device.get("subsystem") != self.subsystem:
            return False

        if self.vendor_id:
            dev_vid = (device.get("vendor_id") or "").lower()
            if dev_vid != self.vendor_id:
                return False

        if self.product_id:
            dev_pid = (device.get("product_id") or "").lower()
            if dev_pid != self.product_id:
                return False

        if self.serial and device.get("serial") != self.serial:
            return False

        if self.devname_patterns:
            devname = device.get("devname", "")
            if not any(fnmatch.fnmatch(devname, pattern) for pattern in self.devname_patterns):
                return False

        return True


class DeviceFilterEngine:
    """
    Evaluates devices against a collection of filter rules (Whitelist).
    If any rule matches, the device is accepted.
    """
    def __init__(self, rules_config: List[Dict[str, Any]]):
        self.rules: List[FilterRule] = [FilterRule(r) for r in rules_config]

    def is_accepted(self, device: Dict[str, Any]) -> bool:
        """Returns True if device matches at least one whitelist rule."""
        if not self.rules:
            # If no rules specified, reject all for safety
            return False

        return any(rule.matches(device) for rule in self.rules)
