"""
IPC Protocol specifications and message serialization for LXC USB Hotplug.
Uses standard JSON Lines format over Unix Domain Sockets.
"""

import json
import time
from typing import Dict, Any, Optional, List

# Message Types
MSG_HELLO = "HELLO"
MSG_INITIAL_SYNC = "INITIAL_SYNC"
MSG_HOTPLUG_EVENT = "HOTPLUG_EVENT"
MSG_PING = "PING"
MSG_PONG = "PONG"

# Actions
ACTION_ADD = "add"
ACTION_REMOVE = "remove"


def current_iso_timestamp() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def encode_message(payload: Dict[str, Any]) -> bytes:
    """Encodes a Python dictionary into a newline-terminated JSON UTF-8 byte string."""
    return (json.dumps(payload, separators=(',', ':')) + "\n").encode("utf-8")


def decode_message(line: str) -> Optional[Dict[str, Any]]:
    """Decodes a single line into a Python dictionary. Returns None on parse error."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def create_hello_message(vmid: int, version: str = "1.0.0") -> Dict[str, Any]:
    """Generates HELLO message sent by Guest Agent on connect."""
    return {
        "type": MSG_HELLO,
        "vmid": vmid,
        "version": version,
        "timestamp": current_iso_timestamp()
    }


def create_initial_sync_message(seq: int, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates INITIAL_SYNC message sent by Host to Guest containing current active devices."""
    return {
        "type": MSG_INITIAL_SYNC,
        "seq": seq,
        "devices": devices,
        "timestamp": current_iso_timestamp()
    }


def create_hotplug_event_message(seq: int, action: str, device: Dict[str, Any]) -> Dict[str, Any]:
    """Generates HOTPLUG_EVENT message for dynamic add/remove events."""
    return {
        "type": MSG_HOTPLUG_EVENT,
        "seq": seq,
        "action": action,
        "device": device,
        "timestamp": current_iso_timestamp()
    }


def create_ping_message() -> Dict[str, Any]:
    return {"type": MSG_PING, "timestamp": current_iso_timestamp()}


def create_pong_message() -> Dict[str, Any]:
    return {"type": MSG_PONG, "timestamp": current_iso_timestamp()}
