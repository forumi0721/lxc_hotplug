"""
Host Agent main daemon loop.
Coordinates Netlink listener, device cache, cgroup permissions, and IPC server.
Host's actual /dev is mounted directly into container as /dev/.lxc/dev.
"""

import os
import sys
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

    def _on_guest_connected(self, client: ClientConnection):
        """Sends full initial snapshot when a guest connects."""
        devices = self.cache.get_all()
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

            # Process permissions and dispatch to containers
            for c_info in self.containers:
                if not c_info.get("enabled", True):
                    continue
                vmid = c_info.get("vmid")
                if not vmid:
                    continue

                allowed = self.cgroup.ensure_device_access(vmid, devname, major, minor)
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
            msg = create_hotplug_event_message(self._next_seq(), ACTION_REMOVE, device_entry)
            self.server.broadcast_to_all(msg)

    def run(self):
        """Starts Host Agent and enters main I/O event loop."""
        self.logger.info(f"Starting LXC Hotplug Host Agent (config: {self.config_path})...")
        self.logger.info(f"Socket dir: {self.socket_dir}")

        # Setup sockets for each enabled container
        for c_info in self.containers:
            if c_info.get("enabled", True) and "vmid" in c_info:
                vmid = c_info["vmid"]
                self.server.register_vmid(vmid)

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
