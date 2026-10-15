"""
Unified CLI entry point for LXC USB Hotplug.
Supports running either Host Agent or Guest Agent via subcommands.
Uses lazy imports so Host-only or Guest-only standalone packages work without ModuleNotFoundError.
"""

import sys
import argparse
from lxc_hotplug import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="lxc-hotplug",
        description=f"LXC USB Hotplug Daemon v{__version__} (Pure Python 3)"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Agent role to execute")

    # Host subcommand
    host_parser = subparsers.add_parser("host", help="Run Host Agent on Proxmox VE")
    host_parser.add_argument(
        "-c", "--config",
        default="/etc/lxc-hotplug/host.yaml",
        help="Path to host config file (default: /etc/lxc-hotplug/host.yaml)"
    )

    # Guest subcommand
    guest_parser = subparsers.add_parser("guest", help="Run Guest Agent in Privileged LXC Container")
    guest_parser.add_argument(
        "-c", "--config",
        default="/etc/lxc-hotplug/guest.yaml",
        help="Path to guest config file (default: /etc/lxc-hotplug/guest.yaml)"
    )

    args = parser.parse_args()

    if args.subcommand == "host":
        try:
            from lxc_hotplug.host.daemon import HostAgentDaemon
        except ImportError as e:
            print(f"Error: Host Agent module not found in this package ({e}).", file=sys.stderr)
            sys.exit(1)
        daemon = HostAgentDaemon(config_path=args.config)
        daemon.run()
    elif args.subcommand == "guest":
        try:
            from lxc_hotplug.guest.daemon import GuestAgentDaemon
        except ImportError as e:
            print(f"Error: Guest Agent module not found in this package ({e}).", file=sys.stderr)
            sys.exit(1)
        daemon = GuestAgentDaemon(config_path=args.config)
        daemon.run()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
