"""
Wait for the network to come back.

On this setup (VPN over a phone hotspot) DNS sometimes drops out for minutes
at a time. Fixed short retries give up long before it returns, so callers that
see a network error wait here until the hosts they need resolve again.

    python -m fixgenie.common.network            # wait up to 15 min, exit 0 if online
    python -m fixgenie.common.network --max-wait 60
"""
from __future__ import annotations

import argparse
import socket
import sys
import time

# The hosts the pipeline can't run without: Google auth + Sheets, the email API.
DEFAULT_HOSTS = ("oauth2.googleapis.com", "sheets.googleapis.com", "api.brevo.com")


def is_online(hosts: tuple[str, ...] | list[str] = DEFAULT_HOSTS) -> bool:
    """True if every host resolves right now."""
    for host in hosts:
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            return False
    return True


def wait_for_network(
    hosts: tuple[str, ...] | list[str] = DEFAULT_HOSTS,
    max_wait: float = 900,
    interval: float = 15,
    log=print,
) -> bool:
    """
    Block until every host resolves, or `max_wait` seconds pass.
    Returns True if the network is up, False if it never came back.
    """
    if is_online(hosts):
        return True
    start = time.monotonic()
    log(f"Network down (can't resolve {', '.join(hosts)}); waiting up to {max_wait / 60:.0f} min...")
    while time.monotonic() - start < max_wait:
        time.sleep(interval)
        if is_online(hosts):
            log(f"Network back after {time.monotonic() - start:.0f}s.")
            return True
    log(f"Network still down after {max_wait / 60:.0f} min.")
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Wait until DNS works again.")
    ap.add_argument("--max-wait", type=float, default=900, help="Seconds to wait (default 900).")
    ap.add_argument("--interval", type=float, default=15, help="Seconds between checks.")
    ap.add_argument("hosts", nargs="*", help="Hosts to check (default: Google + Brevo).")
    args = ap.parse_args()
    hosts = tuple(args.hosts) or DEFAULT_HOSTS
    sys.exit(0 if wait_for_network(hosts, args.max_wait, args.interval) else 1)


if __name__ == "__main__":
    main()
