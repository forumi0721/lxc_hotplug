"""
Device Node Operator for Guest Agent.
Performs privileged mknod and idempotent unlink on target /dev paths.
Supports inspecting shared mount directory (/dev/.lxc/dev) and replicating identical nodes.
"""

import os
import stat
import logging
from typing import Optional


class DeviceNodeEngine:
    """
    Creates and deletes character device nodes in the container filesystem.
    """
    def __init__(self, target_dev_dir: str = "/dev", logger: Optional[logging.Logger] = None):
        self.target_dev_dir = target_dev_dir
        self.logger = logger or logging.getLogger("DeviceNodeEngine")

    def create_node(self, devname: str, major: int, minor: int) -> bool:
        """Creates a character device node at target_dev_dir/devname."""
        target_path = os.path.join(self.target_dev_dir, devname)
        parent_dir = os.path.dirname(target_path)

        try:
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, mode=0o755, exist_ok=True)

            # Idempotent cleanup if already exists
            if os.path.exists(target_path):
                os.unlink(target_path)

            mode = stat.S_IFCHR | 0o660
            dev = os.makedev(major, minor)
            os.mknod(target_path, mode, dev)
            os.chmod(target_path, 0o660)
            self.logger.info(f"Created device node: {target_path} (c {major}:{minor})")
            return True
        except PermissionError:
            self.logger.error(
                f"Permission denied creating {target_path}. Ensure container is Privileged (unprivileged: 0)."
            )
            return False
        except OSError as e:
            self.logger.error(f"Failed to create {target_path}: {e}")
            return False

    def create_node_from_shared(
        self,
        devname: str,
        shared_dev_dir: str,
        fallback_major: Optional[int] = None,
        fallback_minor: Optional[int] = None
    ) -> bool:
        """
        Inspects the device node in shared_dev_dir/devname placed by Host,
        reads its stat (major/minor), and replicates it in target_dev_dir/devname using mknod.
        """
        shared_path = os.path.join(shared_dev_dir, devname)
        if not os.path.exists(shared_path):
            if fallback_major is not None and fallback_minor is not None:
                self.logger.warning(
                    f"Shared node not found at {shared_path}. Falling back to IPC major:minor ({fallback_major}:{fallback_minor})"
                )
                return self.create_node(devname, fallback_major, fallback_minor)
            self.logger.error(f"Shared device node not found at {shared_path}")
            return False

        try:
            st = os.stat(shared_path)
            if not stat.S_ISCHR(st.st_mode):
                self.logger.warning(f"Shared node {shared_path} is not a character device (mode={oct(st.st_mode)})")

            major = os.major(st.st_rdev)
            minor = os.minor(st.st_rdev)
            self.logger.info(f"Inspected shared device at {shared_path} -> c {major}:{minor}")
            return self.create_node(devname, major, minor)
        except OSError as e:
            self.logger.error(f"Failed to inspect shared device {shared_path}: {e}")
            if fallback_major is not None and fallback_minor is not None:
                return self.create_node(devname, fallback_major, fallback_minor)
            return False

    def remove_node(self, devname: str) -> bool:
        """Removes device node if present (idempotent)."""
        target_path = os.path.join(self.target_dev_dir, devname)
        try:
            if os.path.exists(target_path):
                os.unlink(target_path)
                self.logger.info(f"Removed device node: {target_path}")
            return True
        except OSError as e:
            self.logger.error(f"Failed to remove {target_path}: {e}")
            return False
