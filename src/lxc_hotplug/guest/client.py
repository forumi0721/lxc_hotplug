"""
Guest IPC Client with automatic reconnection and exponential backoff.
"""

import os
import time
import socket
import logging
from typing import Optional, List, Dict, Any

from lxc_hotplug.common.protocol import (
    MSG_HELLO, MSG_INITIAL_SYNC, MSG_HOTPLUG_EVENT, MSG_PING, MSG_PONG,
    encode_message, decode_message, create_hello_message, create_pong_message
)
from lxc_hotplug.common.socket_utils import LineStreamBuffer


class GuestIPCClient:
    """
    Connects to the Host Agent's Unix Domain Socket and handles reconnection.
    """
    def __init__(self, socket_path: str, vmid: int, logger: Optional[logging.Logger] = None):
        self.socket_path = socket_path
        self.vmid = vmid
        self.logger = logger or logging.getLogger("GuestIPCClient")

        self.sock: Optional[socket.socket] = None
        self.buffer = LineStreamBuffer()
        self.is_connected: bool = False

        self._backoff = 2.0
        self._max_backoff = 30.0
        self._last_connect_attempt = 0.0
        self._warned_missing_socket = False

    @property
    def fileno(self) -> int:
        if not self.sock:
            return -1
        return self.sock.fileno()

    def try_connect(self) -> bool:
        """Attempts connection if not currently connected and backoff time passed."""
        if self.is_connected:
            return True

        now = time.monotonic()
        if now - self._last_connect_attempt < self._backoff:
            return False

        self._last_connect_attempt = now
        if not os.path.exists(self.socket_path):
            if not self._warned_missing_socket:
                self.logger.warning(
                    f"Host socket not found: {self.socket_path}. "
                    f"Please verify host agent is active and /run/lxc-hotplug is mounted from host. Retrying in background..."
                )
                self._warned_missing_socket = True
            else:
                self.logger.debug(f"Host socket does not exist yet: {self.socket_path}. Retrying in {self._backoff:.1f}s...")
            self._increase_backoff()
            return False

        self._warned_missing_socket = False

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.setblocking(False)
            s.connect(self.socket_path)
        except BlockingIOError:
            pass  # Nonblocking connect in progress
        except OSError as e:
            self.logger.debug(f"Connect failed ({e}). Retrying in {self._backoff:.1f}s...")
            self._increase_backoff()
            return False

        self.sock = s
        self.is_connected = True
        self._backoff = 2.0  # Reset backoff on success
        self.buffer.clear()
        self.logger.info(f"Successfully connected to Host Agent: {self.socket_path}")

        # Send initial handshake
        self.send_message(create_hello_message(self.vmid))
        return True

    def _increase_backoff(self):
        self._backoff = min(self._backoff * 1.5, self._max_backoff)

    def send_message(self, message: Dict[str, Any]):
        """Sends a JSON message to host."""
        if not self.is_connected or not self.sock:
            return
        try:
            data = encode_message(message)
            self.sock.sendall(data)
        except OSError as e:
            self.logger.warning(f"Socket send error: {e}. Disconnecting.")
            self.disconnect()

    def receive_messages(self) -> List[Dict[str, Any]]:
        """Reads pending data and returns a list of decoded message dictionaries."""
        if not self.is_connected or not self.sock:
            return []

        try:
            chunk = self.sock.recv(4096)
            if not chunk:
                self.logger.warning("Host Agent closed connection.")
                self.disconnect()
                return []

            lines = self.buffer.feed(chunk)
            messages = []
            for line in lines:
                msg = decode_message(line)
                if msg:
                    messages.append(msg)
            return messages
        except (BlockingIOError, InterruptedError):
            return []
        except OSError as e:
            self.logger.warning(f"Socket read error: {e}. Disconnecting.")
            self.disconnect()
            return []

    def disconnect(self):
        """Closes socket and resets state."""
        self.is_connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.buffer.clear()
