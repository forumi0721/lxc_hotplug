"""
Active Device Cache for the Host Agent.
Maintains in-memory state of connected devices to enrich Remove events and provide Initial Sync snapshots.
"""

from typing import Dict, Any, List, Optional


class ActiveDeviceCache:
    """
    Stores active USB devices indexed by devpath.
    Guarantees stateful persistence across dynamic plug/unplug cycles.
    """
    def __init__(self):
        # devpath -> device_dict
        self._devices: Dict[str, Dict[str, Any]] = {}

    def add(self, devpath: str, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """Registers or updates a device in cache and returns the stored data."""
        self._devices[devpath] = dict(device_data)
        return self._devices[devpath]

    def remove(self, devpath: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the enriched device data for devpath and deletes it from cache.
        Returns None if devpath is not in cache (cache miss).
        """
        return self._devices.pop(devpath, None)

    def get(self, devpath: str) -> Optional[Dict[str, Any]]:
        """Looks up a device by devpath."""
        return self._devices.get(devpath)

    def get_all(self) -> List[Dict[str, Any]]:
        """Returns a snapshot list of all currently active devices."""
        return list(self._devices.values())

    def clear(self):
        self._devices.clear()
