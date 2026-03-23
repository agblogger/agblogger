"""Network utility functions shared across the backend."""

from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)


def is_trusted_proxy(client_ip: str, trusted_ips: list[str]) -> bool:
    """Check whether *client_ip* matches any entry in *trusted_ips*.

    Entries may be exact IP addresses (IPv4 or IPv6) or CIDR network
    strings.  Comparison is performed on parsed ``ipaddress`` objects so
    that equivalent representations (e.g. ``"::1"`` vs
    ``"0:0:0:0:0:0:0:1"``) are treated as equal.

    Malformed entries are skipped and a warning is logged so operators
    can spot configuration mistakes without crashing the server.
    """
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in trusted_ips:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if addr == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            logger.warning("Malformed trusted proxy entry: %s", entry)
            continue
    return False
