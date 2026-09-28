"""
Netlink Kobject Uevent listener using pure Python standard library.
"""

import os
import socket
from typing import Dict, Optional, Tuple, Callable

NETLINK_KOBJECT_UEVENT = 15


class NetlinkUeventListener:
    """
    Listens to raw kernel uevents directly via Netlink socket without external libudev.
    """
    def __init__(self, buffer_size: int = 8192):
        self._buffer_size = buffer_size
        self._socket: Optional[socket.socket] = None

    def start(self):
        """Initializes and binds the Netlink raw socket."""
        self._socket = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_KOBJECT_UEVENT)
        self._socket.setblocking(False)
        # Bind to PID and multicast group 1 (uevent multicast group)
        self._socket.bind((os.getpid(), 1))

    @property
    def fileno(self) -> int:
        if self._socket is None:
            raise RuntimeError("Netlink socket not started")
        return self._socket.fileno()

    def receive_event(self) -> Optional[Dict[str, str]]:
        """
        Receives and parses a single pending uevent packet.
        Returns a dict of environment variables or None if no packet is ready.
        """
        if self._socket is None:
            return None

        try:
            data = self._socket.recv(self._buffer_size)
        except (BlockingIOError, InterruptedError):
            return None
        except socket.error:
            return None

        if not data:
            return None

        # Uevent data is formatted as null-terminated strings: ACTION=add\0DEVPATH=...\0
        lines = [item.decode("utf-8", errors="replace") for item in data.split(b"\0") if item]
        env: Dict[str, str] = {}
        for line in lines:
            if "=" in line:
                key, val = line.split("=", 1)
                env[key] = val

        return env

    def close(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
