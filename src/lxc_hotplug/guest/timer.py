"""
Monotonic debounce timer engine for Guest Agent.
Coordinates 10s initial window, +5s extension, and 3s inactivity settlement.
"""

import time
import logging
from typing import Callable, Optional


class DebounceTimerEngine:
    """
    Manages monitoring windows and debouncing logic.
    """
    def __init__(
        self,
        on_settled_callback: Callable[[], None],
        initial_window_sec: float = 10.0,
        extend_window_sec: float = 5.0,
        max_window_sec: float = 30.0,
        inactivity_sec: float = 3.0,
        logger: Optional[logging.Logger] = None
    ):
        self.callback = on_settled_callback
        self.initial_window = initial_window_sec
        self.extend_window = extend_window_sec
        self.max_window = max_window_sec
        self.inactivity_threshold = inactivity_sec
        self.logger = logger or logging.getLogger("DebounceTimer")

        self.is_monitoring: bool = False
        self.start_time: float = 0.0
        self.deadline: float = 0.0
        self.last_activity: float = 0.0

    def on_device_event(self):
        """Called when an accepted device add/remove event occurs."""
        now = time.monotonic()
        self.last_activity = now

        if not self.is_monitoring:
            self.is_monitoring = True
            self.start_time = now
            self.deadline = now + self.initial_window
            self.logger.info(
                f"Monitoring started ({self.initial_window:.1f}s window, settle on {self.inactivity_threshold:.1f}s inactivity)"
            )
        else:
            old_deadline = self.deadline
            max_allowed = self.start_time + self.max_window
            self.deadline = min(self.deadline + self.extend_window, max_allowed)
            self.logger.info(
                f"Monitoring extended (+{self.extend_window:.1f}s, remaining: {self.deadline - now:.1f}s)"
            )

    def check_tick(self):
        """Periodically called by main loop (e.g. every 100ms) to check timers."""
        if not self.is_monitoring:
            return

        now = time.monotonic()
        time_since_last_activity = now - self.last_activity
        time_remaining = self.deadline - now

        # Condition 1: Settled after inactivity period
        # Condition 2: Overall deadline reached
        if (time_since_last_activity >= self.inactivity_threshold) or (time_remaining <= 0):
            reason = "Inactivity settled" if (time_since_last_activity >= self.inactivity_threshold) else "Max deadline reached"
            self.logger.info(f"Monitoring completed ({reason}). Triggering post-actions...")
            self.is_monitoring = False
            try:
                self.callback()
            except Exception as e:
                self.logger.error(f"Error in post-trigger callback: {e}")
