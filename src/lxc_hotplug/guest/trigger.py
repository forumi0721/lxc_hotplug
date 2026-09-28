"""
Post-trigger Engine for Guest Agent.
Executes udevadm trigger and optional custom hook scripts upon device stabilization.
"""

import os
import subprocess
import logging
from typing import Optional


class PostTriggerEngine:
    """
    Executes post-stabilization actions in the container.
    """
    def __init__(
        self,
        enable_udevadm: bool = True,
        hook_script: Optional[str] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.enable_udevadm = enable_udevadm
        self.hook_script = hook_script
        self.logger = logger or logging.getLogger("PostTriggerEngine")

    def execute_triggers(self):
        """Runs configured triggers."""
        # 1. udevadm trigger
        if self.enable_udevadm:
            self._run_udevadm_trigger()

        # 2. Custom hook script
        if self.hook_script:
            self._run_hook_script()

    def _run_udevadm_trigger(self):
        try:
            self.logger.info("Executing: udevadm trigger")
            res = subprocess.run(
                ["udevadm", "trigger"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            if res.returncode != 0:
                self.logger.warning(f"udevadm trigger returned code {res.returncode}: {res.stderr.strip()}")
            else:
                self.logger.info("udevadm trigger completed successfully.")
        except FileNotFoundError:
            self.logger.debug("udevadm binary not found in container. Skipping.")
        except Exception as e:
            self.logger.warning(f"udevadm trigger error (ignoring): {e}")

    def _run_hook_script(self):
        if not self.hook_script or not os.path.exists(self.hook_script):
            self.logger.warning(f"Hook script not found: {self.hook_script}")
            return

        if not os.access(self.hook_script, os.X_OK):
            self.logger.warning(f"Hook script is not executable: {self.hook_script}")
            return

        try:
            self.logger.info(f"Executing hook script: {self.hook_script}")
            res = subprocess.run(
                [self.hook_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            self.logger.info(f"Hook script completed (code {res.returncode})")
        except Exception as e:
            self.logger.error(f"Error executing hook script: {e}")
