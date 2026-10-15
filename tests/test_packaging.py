"""
Unit tests for package integrity and metadata format across distributions.
"""

import os
import tarfile
import subprocess
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(ROOT_DIR, "dist")


class TestArchPackageIntegrity(unittest.TestCase):
    def setUp(self):
        # Ensure build-packages.py has run for arch
        subprocess.run(
            ["python3", os.path.join(ROOT_DIR, "scripts", "build-packages.py"), "arch"],
            check=True,
            capture_output=True
        )

    def _verify_arch_package(self, pkg_path: str, expected_pkgname: str):
        self.assertTrue(os.path.exists(pkg_path), f"Package does not exist: {pkg_path}")

        # Decompress zstd to tar stream using subprocess
        proc = subprocess.Popen(
            ["zstd", "-dc", pkg_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            members = []
            pkginfo_data = None
            for member in tar:
                members.append(member.name)
                # Verify no entry has './' prefix (pacman libalpm requirement)
                self.assertFalse(
                    member.name.startswith("./"),
                    f"Entry '{member.name}' has './' prefix, which breaks pacman libalpm parsing!"
                )
                if member.name == ".PKGINFO":
                    f = tar.extractfile(member)
                    if f:
                        pkginfo_data = f.read().decode("utf-8")

        proc.stdout.close()
        proc.stderr.close()
        proc.wait()
        self.assertEqual(proc.returncode, 0, "zstd decompression failed")

        # Verify essential root metadata files
        self.assertIn(".PKGINFO", members, ".PKGINFO must be at the root of the archive")
        self.assertIn(".BUILDINFO", members, ".BUILDINFO must be at the root of the archive")
        self.assertIn(".INSTALL", members, ".INSTALL scriptlet must be at the root of the archive")

        # Verify .PKGINFO key-value contents
        self.assertIsNotNone(pkginfo_data, ".PKGINFO file could not be read")
        kv = {}
        for line in pkginfo_data.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if " = " in line:
                k, v = line.split(" = ", 1)
                kv[k] = v

        self.assertEqual(kv.get("pkgname"), expected_pkgname)
        self.assertEqual(kv.get("pkgbase"), expected_pkgname)
        self.assertTrue("-" in kv.get("pkgver", ""), "pkgver must contain a hyphen (e.g. 1.0.0-1)")
        self.assertEqual(kv.get("arch"), "any")

    def test_guest_arch_package(self):
        pkg_file = os.path.join(DIST_DIR, "lxc-hotplug-guest-1.0.0-1-any.pkg.tar.zst")
        self._verify_arch_package(pkg_file, "lxc-hotplug-guest")

    def test_host_arch_package(self):
        pkg_file = os.path.join(DIST_DIR, "lxc-hotplug-host-1.0.0-1-any.pkg.tar.zst")
        self._verify_arch_package(pkg_file, "lxc-hotplug-host")


if __name__ == "__main__":
    unittest.main()
