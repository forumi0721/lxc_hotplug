"""
Unit tests for LXC USB Hotplug components.
"""

import unittest
import time
import os
import tempfile

from lxc_hotplug.common.protocol import (
    encode_message, decode_message,
    create_hello_message, create_initial_sync_message, create_hotplug_event_message,
    MSG_HELLO, MSG_INITIAL_SYNC, MSG_HOTPLUG_EVENT, ACTION_ADD, ACTION_REMOVE
)
from lxc_hotplug.common.socket_utils import LineStreamBuffer
from lxc_hotplug.common.config import load_config
from lxc_hotplug.guest.filter import DeviceFilterEngine
from lxc_hotplug.guest.timer import DebounceTimerEngine
from lxc_hotplug.host.cache import ActiveDeviceCache


class TestProtocol(unittest.TestCase):
    def test_encode_decode(self):
        msg = create_hello_message(100, "1.0.0")
        raw = encode_message(msg)
        self.assertTrue(raw.endswith(b"\n"))

        decoded = decode_message(raw.decode("utf-8"))
        self.assertEqual(decoded["type"], MSG_HELLO)
        self.assertEqual(decoded["vmid"], 100)


class TestSocketBuffer(unittest.TestCase):
    def test_line_stream_buffer(self):
        buf = LineStreamBuffer()
        # Feed partial chunk
        lines = buf.feed(b'{"type":"PING"')
        self.assertEqual(len(lines), 0)

        # Feed remaining chunk with newline and another message
        lines = buf.feed(b'}\n{"type":"PONG"}\n')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], '{"type":"PING"}')
        self.assertEqual(lines[1], '{"type":"PONG"}')


class TestFilterEngine(unittest.TestCase):
    def setUp(self):
        rules = [
            {"subsystem": "tty", "devname_pattern": "ttyACM*|ttyUSB*"},
            {"subsystem": "sound", "vendor_id": "0d8c", "product_id": "0014"},
            {"subsystem": "hidraw", "vendor_id": "046d"}
        ]
        self.engine = DeviceFilterEngine(rules)

    def test_whitelist_matches(self):
        # Match ttyUSB
        dev1 = {"subsystem": "tty", "devname": "ttyUSB0", "vendor_id": "10c4", "product_id": "ea60"}
        self.assertTrue(self.engine.is_accepted(dev1))

        # Match sound card with exact VID/PID
        dev2 = {"subsystem": "sound", "devname": "snd/controlC1", "vendor_id": "0d8c", "product_id": "0014"}
        self.assertTrue(self.engine.is_accepted(dev2))

        # Reject sound card with wrong PID
        dev3 = {"subsystem": "sound", "devname": "snd/controlC2", "vendor_id": "0d8c", "product_id": "9999"}
        self.assertFalse(self.engine.is_accepted(dev3))

        # Reject unlisted subsystem
        dev4 = {"subsystem": "block", "devname": "sda", "vendor_id": "abcd"}
        self.assertFalse(self.engine.is_accepted(dev4))


class TestDebounceTimer(unittest.TestCase):
    def test_inactivity_settle(self):
        triggered = []

        def callback():
            triggered.append(True)

        # Fast timer for testing: 0.5s initial, 0.2s extend, 1.0s max, 0.2s inactivity
        timer = DebounceTimerEngine(
            on_settled_callback=callback,
            initial_window_sec=0.5,
            extend_window_sec=0.2,
            max_window_sec=1.0,
            inactivity_sec=0.2
        )

        timer.on_device_event()
        self.assertTrue(timer.is_monitoring)

        # Simulate 0.1s passing (not settled yet)
        time.sleep(0.1)
        timer.check_tick()
        self.assertEqual(len(triggered), 0)

        # Simulate another event (extends)
        timer.on_device_event()
        self.assertTrue(timer.is_monitoring)

        # Wait 0.25s (inactivity threshold reached)
        time.sleep(0.25)
        timer.check_tick()
        self.assertEqual(len(triggered), 1)
        self.assertFalse(timer.is_monitoring)


class TestDeviceCache(unittest.TestCase):
    def test_cache_add_remove(self):
        cache = ActiveDeviceCache()
        devpath = "/devices/pci0000:00/ttyUSB0"
        data = {
            "subsystem": "tty",
            "devname": "ttyUSB0",
            "vendor_id": "10c4",
            "product_id": "ea60"
        }
        cache.add(devpath, data)
        self.assertEqual(len(cache.get_all()), 1)

        removed = cache.remove(devpath)
        self.assertIsNotNone(removed)
        self.assertEqual(removed["vendor_id"], "10c4")
        self.assertEqual(len(cache.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
