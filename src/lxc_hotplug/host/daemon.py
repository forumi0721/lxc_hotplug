"""
Host Agent main daemon loop.
Coordinates Netlink listener, device cache, cgroup permissions, shared dev mirroring, and IPC server.
"""

import os
import sys
import stat
import select
import signal
import logging
from typing import Dict, Any, List

from lxc_hotplug.common.logger import setup_logger
from lxc_hotplug.common.config import load_config
from lxc_hotplug.common.protocol import (
    ACTION_ADD, ACTION_REMOVE,
    create_initial_sync_message, create_hotplug_event_message
)
from lxc_hotplug.host.netlink import NetlinkUeventListener
from lxc_hotplug.host.sysfs import resolve_usb_metadata
from lxc_hotplug.host.cache import ActiveDeviceCache
from lxc_hotplug.host.cgroup import CgroupManager
from lxc_hotplug.host.server import HostIPCServer, ClientConnection


class HostAgentDaemon:
    def __init__(self, config_path: str):
        self.logger = setup_logger("HostAgent")
        self.config_path = config_path
        self.config = load_config(config_path)

        self.socket_dir = self.config.get("socket_dir", "/run/lxc-hotplug")
        self.shared_dev_base = self.config.get("shared_dev_base", "/dev/.lxc/dev")
        self.monitored_subsystems = set(self.config.get("subsystems", ["hidraw", "hiddev", "tty", "sound"]))
        self.containers = self.config.get("containers", [])

        self.seq = 0
        self.running = False

        self.cache = ActiveDeviceCache()
        self.cgroup = CgroupManager(
            dynamic_inject=self.config.get("dynamic_cgroup_inject", True),
            logger=self.logger
        )
        self.server = HostIPCServer(socket_dir=self.socket_dir, logger=self.logger)
        self.netlink = NetlinkUeventListener()

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def _mirror_node_to_shared_dir(self, vmid: int, devname: str, major: int, minor: int):
        """Creates/mirrors character device node in /dev/.lxc/dev/<vmid>/<devname>."""
        shared_node_path = os.path.join(self.shared_dev_base, str(vmid), devname)
        try:
            os.makedirs(os.path.dirname(shared_node_path), exist_ok=True)
            if os.path.exists(shared_node_path):
                os.unlink(shared_node_path)
            mode = stat.S_IFCHR | 0o660
            dev = os.makedev(major, minor)
            os.mknod(shared_node_path, mode, dev)
            os.chmod(shared_node_path, 0o660)
            self.logger.debug(f"[VMID {vmid}] Mirrored shared device node: {shared_node_path} (c {major}:{minor})")
        except OSError as e:
            self.logger.warning(f"[VMID {vmid}] Failed to mirror shared node {shared_node_path}: {e}")

    def _unmirror_node_from_shared_dir(self, vmid: int, devname: str):
        """Removes mirrored node in /dev/.lxc/dev/<vmid>/<devname>."""
        shared_node_path = os.path.join(self.shared_dev_base, str(vmid), devname)
        try:
            if os.path.exists(shared_node_path):
                os.unlink(shared_node_path)
                self.logger.debug(f"[VMID {vmid}] Cleaned up shared node: {shared_node_path}")
        except OSError as e:
            self.logger.debug(f"[VMID {vmid}] Error unlinking shared node {shared_node_path}: {e}")

    def _on_guest_connected(self, client: ClientConnection):
        """Sends full initial snapshot when a guest connects, ensuring shared nodes exist."""
        devices = self.cache.get_all()
        # Ensure all cached devices are mirrored into this container's shared dev dir
        for dev in devices:
            devname = dev.get("devname")
            major = dev.get("major")
            minor = dev.get("minor")
            if devname and major is not None and minor is not None:
                self._mirror_node_to_shared_dir(client.vmid, devname, major, minor)

        sync_msg = create_initial_sync_message(self._next_seq(), devices)
        client.send(sync_msg)
        self.logger.info(
            f"[VMID {client.vmid}] Initial sync sent: {len(devices)} active device(s)"
        )

    def _process_uevent(self, env: Dict[str, str]):
        action = env.get("ACTION")
        subsystem = env.get("SUBSYSTEM")
        devname = env.get("DEVNAME")
        devpath = env.get("DEVPATH")

        if not action or not subsystem or not devname or not devpath:
            return

        # Check if subsystem is in monitored list
        if subsystem not in self.monitored_subsystems:
            return

        major = int(env.get("MAJOR", 0))
        minor = int(env.get("MINOR", 0))

        if action == ACTION_ADD:
            metadata = resolve_usb_metadata(devpath)
            device_entry = {
                "subsystem": subsystem,
                "devname": devname,
                "devpath": devpath,
                "major": major,
                "minor": minor,
                "vendor_id": metadata["vendor_id"],
                "product_id": metadata["product_id"],
                "vendor": metadata["vendor"],
                "product": metadata["product"],
                "serial": metadata["serial"],
                "cgroup_allowed": True
            }

            # Register in cache
            self.cache.add(devpath, device_entry)
            self.logger.info(
                f"[UEVENT ADD] {subsystem}/{devname} (VID:{metadata['vendor_id']}, PID:{metadata['product_id']})"
            )

            # Process permissions, mirror to /dev/.lxc/dev, and dispatch to containers
            for c_info in self.containers:
                if not c_info.get("enabled", True):
                    continue
                vmid = c_info.get("vmid")
                if not vmid:
                    continue

                allowed = self.cgroup.ensure_device_access(vmid, devname, major, minor)
                # Place node in /dev/.lxc/dev/<vmid>/<devname>
                self._mirror_node_to_shared_dir(vmid, devname, major, minor)

                event_payload = dict(device_entry)
                event_payload["cgroup_allowed"] = allowed
                msg = create_hotplug_event_message(self._next_seq(), ACTION_ADD, event_payload)
                self.server.broadcast_to_vmid(vmid, msg)

        elif action == ACTION_REMOVE:
            cached = self.cache.remove(devpath)
            if cached:
                device_entry = cached
            else:
                # Fallback on cache miss
                device_entry = {
                    "subsystem": subsystem,
                    "devname": devname,
                    "devpath": devpath,
                    "major": major,
                    "minor": minor,
                    "vendor_id": None,
                    "product_id": None,
                    "vendor": None,
                    "product": None,
                    "serial": None,
                    "cgroup_allowed": True
                }

            self.logger.info(
                f"[UEVENT REMOVE] {subsystem}/{devname} (cached={cached is not None})"
            )

            # Remove mirrored nodes in /dev/.lxc/dev/<vmid>/<devname>
            for c_info in self.containers:
                vmid = c_info.get("vmid")
                if vmid:
                    self._unmirror_node_from_shared_dir(vmid, devname)

            msg = create_hotplug_event_message(self._next_seq(), ACTION_REMOVE, device_entry)
            self.server.broadcast_to_all(msg)

    def run(self):
        """Starts Host Agent and enters main I/O event loop."""
        self.logger.info(f"Starting LXC Hotplug Host Agent (config: {self.config_path})...")
        self.logger.info(f"Shared dev base: {self.shared_dev_base}, Socket dir: {self.socket_dir}")

        # Setup sockets and shared dirs for each enabled container
        for c_info in self.containers:
            if c_info.get("enabled", True) and "vmid" in c_info:
                vmid = c_info["vmid"]
                self.server.register_vmid(vmid)
                os.makedirs(os.path.join(self.shared_dev_base, str(vmid)), mode=0o755, exist_ok=True)

        self.netlink.start()
        self.running = True

        def _signal_handler(signum, frame):
            self.logger.info(f"Shutdown signal received ({signum}). Exiting...")
            self.running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while self.running:
            server_socks = self.server.get_server_sockets()
            client_socks = self.server.get_client_sockets()
            read_fds = [self.netlink.fileno] + server_socks + client_socks

            try:
                readable, _, _ = select.select(read_fds, [], [], 1.0)
            except (InterruptedError, select.error):
                continue

            for fd in readable:
                if fd == self.netlink.fileno:
                    env = self.netlink.receive_event()
                    if env:
                        self._process_uevent(env)
                elif fd in server_socks:
                    # New guest connection
                    self.server.handle_new_connection(fd, self._on_guest_connected)
                elif fd in client_socks:
                    # Client data or disconnect
                    self.server.handle_client_data(fd)

        # Cleanup
        self.logger.info("Cleaning up sockets and listeners...")
        self.netlink.close()
        self.server.close()
        self.logger.info("Host Agent stopped.")
