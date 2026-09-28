"""
Socket utilities and line-buffered stream parser for Unix Domain Sockets.
"""

import os
import socket
from typing import List, Optional


class LineStreamBuffer:
    """
    Accumulates incoming socket byte streams and extracts complete newline-delimited lines.
    Handles partial reads and multiple messages in a single packet.
    """
    def __init__(self):
        self._buffer = b""

    def feed(self, chunk: bytes) -> List[str]:
        """Appends new bytes and returns a list of completed lines (decoded as UTF-8)."""
        if not chunk:
            return []
        self._buffer += chunk
        lines = []
        while b"\n" in self._buffer:
            line_bytes, self._buffer = self._buffer.split(b"\n", 1)
            try:
                line_str = line_bytes.decode("utf-8").strip()
                if line_str:
                    lines.append(line_str)
            except UnicodeDecodeError:
                pass  # Skip corrupted frames
        return lines

    def clear(self):
        self._buffer = b""


def ensure_socket_dir(socket_path: str, mode: int = 0o755):
    """Ensures parent directory for socket exists with safe permissions."""
    parent_dir = os.path.dirname(socket_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, mode=mode, exist_ok=True)


def safe_unlink_socket(socket_path: str):
    """Safely removes an existing socket file if present."""
    try:
        if os.path.exists(socket_path):
            os.unlink(socket_path)
    except OSError:
        pass
