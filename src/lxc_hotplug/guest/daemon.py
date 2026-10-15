"""
Guest Agent main daemon loop.
Coordinates IPC client, rule filter, node operator, debounce timer, and post-triggers.
Inspects mounted host /dev (/dev/.lxc/dev) and replicates identical nodes into container's /dev.
"""

import sys
import select
import signal
import logging
from typing import Dict, Any, List

from lxc_hotplug.common.logger import setup_logger
from lxc_hotplug.common.config import load_config
from lxc_hotplug.common.protocol import (
    MSG_INITIAL_SYNC, MSG_HOTPLUG_EVENT, ACTION_ADD, ACTION_REMOVE
)
from lxc_hotplug.guest.filter import DeviceFilterEngine
from lxc_hotplug.guest.mknod import DeviceNodeEngine
from lxc_hotplug.guest.timer import DebounceTimerEngine
from lxc_hotplug.guest.trigger import PostTriggerEngine
from lxc_hotplug.guest.client import GuestIPCClient


class GuestAgentDaemon:
    def __init__(self, config_path: str):
        self.logger = setup_logger("GuestAgent")
        self.config_path = config_path
        self.config = load_config(config_path)

        self.vmid = int(self.config.get("vmid", 0))
        self.socket_path = self.config.get("socket_path", f"/run/lxc-hotplug/{self.vmid}.sock")
        self.target_dev_dir = self.config.get("target_dev_dir", "/dev")
        # /dev/.lxc/dev is the mount point of host's actual /dev
        self.host_dev_dir = self.config.get("host_dev_dir", "/dev/.lxc/dev")

        # Timer settings
        t_cfg = self.config.get("timer", {})
        init_win = float(t_cfg.get("initial_window_sec", 10.0))
        ext_win = float(t_cfg.get("extend_window_sec", 5.0))
        max_win = float(t_cfg.get("max_window_sec", 30.0))
        inact_win = float(t_cfg.get("inactivity_sec", 3.0))

        # Trigger settings
        trig_cfg = self.config.get("trigger", {})
        enable_udevadm = trig_cfg.get("udevadm_trigger", True)
        hook_script = trig_cfg.get("hook_script")

        # Initialize engines
        self.filter_engine = DeviceFilterEngine(self.config.get("filters", []))
        self.node_engine = DeviceNodeEngine(target_dev_dir=self.target_dev_dir, logger=self.logger)
        self.trigger_engine = PostTriggerEngine(
            enable_udevadm=enable_udevadm,
            hook_script=hook_script,
            logger=self.logger
        )
        self.timer_engine = DebounceTimerEngine(
            on_settled_callback=self.trigger_engine.execute_triggers,
            initial_window_sec=init_win,
            extend_window_sec=ext_win,
            max_window_sec=max_win,
            inactivity_sec=inact_win,
            logger=self.logger
        )
        self.client = GuestIPCClient(socket_path=self.socket_path, vmid=self.vmid, logger=self.logger)
        self.running = False

    def _handle_initial_sync(self, devices: List[Dict[str, Any]]):
        """Processes full snapshot from host upon connection."""
        self.logger.info(f"Processing initial snapshot: {len(devices)} device(s) reported by host.")
        synced_count = 0
        for dev in devices:
            if self.filter_engine.is_accepted(dev):
                devname = dev.get("devname")
                major = dev.get("major")
                minor = dev.get("minor")
                if devname:
                    # Inspect mounted host /dev (/dev/.lxc/dev) and replicate into container /dev
                    if self.node_engine.replicate_from_host_dev(
                        devname=devname,
                        host_dev_dir=self.host_dev_dir,
                        fallback_major=major,
                        fallback_minor=minor
                    ):
                        synced_count += 1
            else:
                self.logger.debug(f"Filtered out initial device: {dev.get('devname')}")

        self.logger.info(f"Initial sync complete. {synced_count} node(s) created in {self.target_dev_dir}.")
        if synced_count > 0:
            self.trigger_engine.execute_triggers()

    def _handle_hotplug_event(self, action: str, dev: Dict[str, Any]):
        """Processes dynamic hotplug event."""
        devname = dev.get("devname")
        major = dev.get("major")
        minor = dev.get("minor")

        if not devname:
            return

        if action == ACTION_ADD:
            if not self.filter_engine.is_accepted(dev):
                self.logger.info(f"[DROP ADD] Device {devname} does not match guest filter rules.")
                return

            self.logger.info(f"[ACCEPT ADD] Replicating from {self.host_dev_dir}/{devname} to {self.target_dev_dir}/{devname}")
            self.node_engine.replicate_from_host_dev(
                devname=devname,
                host_dev_dir=self.host_dev_dir,
                fallback_major=major,
                fallback_minor=minor
            )
            self.timer_engine.on_device_event()

        elif action == ACTION_REMOVE:
            is_matched = self.filter_engine.is_accepted(dev) if (dev.get("vendor_id") or dev.get("subsystem")) else True
            if is_matched:
                self.logger.info(f"[ACCEPT REMOVE] Removing node for {devname}")
                self.node_engine.remove_node(devname)
                self.timer_engine.on_device_event()
            else:
                self.logger.info(f"[DROP REMOVE] Device {devname} does not match guest filter rules.")

    def run(self):
        """Starts Guest Agent daemon loop."""
        self.logger.info(f"Starting LXC Hotplug Guest Agent (VMID {self.vmid}, config: {self.config_path})...")
        self.logger.info(f"Host /dev mount path: {self.host_dev_dir}, Container /dev path: {self.target_dev_dir}")
        self.running = True

        def _signal_handler(signum, frame):
            self.logger.info(f"Shutdown signal received ({signum}). Exiting...")
            self.running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while self.running:
            # Reconnection attempt if disconnected
            if not self.client.is_connected:
                self.client.try_connect()

            # Wait for data or timeout every 100ms
            read_fds = [self.client.fileno] if self.client.is_connected and self.client.fileno >= 0 else []
            try:
                readable, _, _ = select.select(read_fds, [], [], 0.1)
            except (InterruptedError, select.error):
                continue

            if readable:
                messages = self.client.receive_messages()
                for msg in messages:
                    msg_type = msg.get("type")
                    if msg_type == MSG_INITIAL_SYNC:
                        self._handle_initial_sync(msg.get("devices", []))
                    elif msg_type == MSG_HOTPLUG_EVENT:
                        self._handle_hotplug_event(msg.get("action", ""), msg.get("device", {}))

            # Periodic check of debounce timer
            self.timer_engine.check_tick()

        # Cleanup
        self.logger.info("Cleaning up Guest Agent...")
        self.client.disconnect()
        self.logger.info("Guest Agent stopped.")
