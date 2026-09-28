"""
Host IPC Server managing VMID-isolated Unix Domain Sockets.
"""

import os
import socket
import logging
from typing import Dict, List, Optional, Callable, Any

from lxc_hotplug.common.protocol import (
    MSG_HELLO, MSG_PING, MSG_PONG,
    encode_message, decode_message,
    create_initial_sync_message, create_pong_message
)
from lxc_hotplug.common.socket_utils import LineStreamBuffer, ensure_socket_dir, safe_unlink_socket


class ClientConnection:
    """Represents a connected Guest Agent."""
    def __init__(self, sock: socket.socket, vmid: int):
        self.sock = sock
        self.vmid = vmid
        self.buffer = LineStreamBuffer()

    def send(self, payload: Dict[str, Any]):
        """Encodes and sends message to the guest."""
        try:
            data = encode_message(payload)
            self.sock.sendall(data)
        except OSError:
            pass


class HostIPCServer:
    """
    Manages per-VMID listening Unix domain sockets.
    """
    def __init__(self, socket_dir: str = "/run/lxc-hotplug", logger: Optional[logging.Logger] = None):
        self.socket_dir = socket_dir
        self.logger = logger or logging.getLogger("HostIPCServer")
        # vmid -> server_socket
        self._server_sockets: Dict[int, socket.socket] = {}
        # socket_fd -> ClientConnection
        self._clients: Dict[int, ClientConnection] = {}

    def register_vmid(self, vmid: int):
        """Creates and binds listening Unix domain socket for a given VMID."""
        sock_path = os.path.join(self.socket_dir, f"{vmid}.sock")
        ensure_socket_dir(sock_path, mode=0o755)
        safe_unlink_socket(sock_path)

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.setblocking(False)
        server_sock.bind(sock_path)
        # 0660 or 0600 mode for security
        try:
            os.chmod(sock_path, 0o660)
        except OSError:
            pass
        server_sock.listen(5)

        self._server_sockets[vmid] = server_sock
        self.logger.info(f"Listening on Unix socket: {sock_path} (VMID {vmid})")

    def get_server_sockets(self) -> List[socket.socket]:
        return list(self._server_sockets.values())

    def get_client_sockets(self) -> List[socket.socket]:
        return [client.sock for client in self._clients.values()]

    def handle_new_connection(self, server_sock: socket.socket, on_guest_connected: Callable[[ClientConnection], None]):
        """Accepts a new client connection on server_sock."""
        try:
            conn, _ = server_sock.accept()
            conn.setblocking(False)
            # Find which VMID this server socket belongs to
            vmid = next((v for v, s in self._server_sockets.items() if s == server_sock), 0)
            client = ClientConnection(conn, vmid)
            self._clients[conn.fileno()] = client
            self.logger.info(f"[VMID {vmid}] Guest agent connected (fd={conn.fileno()})")
            on_guest_connected(client)
        except OSError:
            pass

    def handle_client_data(self, client_sock: socket.socket) -> Optional[ClientConnection]:
        """Reads incoming data from client. Returns None if client disconnected."""
        fd = client_sock.fileno()
        client = self._clients.get(fd)
        if not client:
            return None

        try:
            data = client_sock.recv(4096)
            if not data:
                self._remove_client(fd)
                return None

            lines = client.buffer.feed(data)
            for line in lines:
                msg = decode_message(line)
                if not msg:
                    continue
                msg_type = msg.get("type")
                if msg_type == MSG_PING:
                    client.send(create_pong_message())
                elif msg_type == MSG_HELLO:
                    self.logger.info(f"[VMID {client.vmid}] Handshake received: version={msg.get('version')}")

            return client
        except (BlockingIOError, InterruptedError):
            return client
        except OSError:
            self._remove_client(fd)
            return None

    def _remove_client(self, fd: int):
        client = self._clients.pop(fd, None)
        if client:
            self.logger.info(f"[VMID {client.vmid}] Guest agent disconnected (fd={fd})")
            try:
                client.sock.close()
            except OSError:
                pass

    def broadcast_to_vmid(self, vmid: int, message: Dict[str, Any]):
        """Sends a message to all connected clients for a given VMID."""
        for client in list(self._clients.values()):
            if client.vmid == vmid:
                client.send(message)

    def broadcast_to_all(self, message: Dict[str, Any]):
        """Sends a message to all connected clients across all VMIDs."""
        for client in list(self._clients.values()):
            client.send(message)

    def close(self):
        """Closes all clients and server listening sockets."""
        for client in list(self._clients.values()):
            self._remove_client(client.sock.fileno())

        for vmid, s in list(self._server_sockets.items()):
            try:
                s.close()
                sock_path = os.path.join(self.socket_dir, f"{vmid}.sock")
                safe_unlink_socket(sock_path)
            except OSError:
                pass
        self._server_sockets.clear()
