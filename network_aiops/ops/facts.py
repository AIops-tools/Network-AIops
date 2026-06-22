"""Read-only device facts via NAPALM getters.

All device-returned text is run through ``sanitize()`` (``s``); returns are
high-signal summaries, not raw blobs. Each function opens a short-lived NAPALM
session, calls one or more getters, and closes it. Per-driver
``NotImplementedError`` becomes a teaching ``NetworkApiError`` via ``getter()``.
"""

from __future__ import annotations

from typing import Any

from network_aiops.connection import device_session
from network_aiops.ops._shared import getter, s


def device_facts(target: Any) -> dict:
    """[READ] Core device facts: hostname, vendor, model, OS version, serial, uptime.

    Returns the interface name list too (use get_interfaces for state/speed).
    """
    with device_session(target) as dev:
        f = getter(target.driver, "get_facts", dev.get_facts)
    return {
        "name": s(target.name, 128),
        "hostname": s(f.get("hostname"), 128),
        "fqdn": s(f.get("fqdn"), 200),
        "vendor": s(f.get("vendor"), 64),
        "model": s(f.get("model"), 128),
        "os_version": s(f.get("os_version"), 200),
        "serial_number": s(f.get("serial_number"), 128),
        "uptime_seconds": int(f.get("uptime") or 0),
        "interface_count": len(f.get("interface_list") or []),
        "interfaces": [s(i, 64) for i in (f.get("interface_list") or [])],
    }


def get_interfaces(target: Any) -> list[dict]:
    """[READ] Interfaces with up/down state, speed, and description."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_interfaces", dev.get_interfaces)
    out: list[dict] = []
    for name, iface in (data or {}).items():
        out.append(
            {
                "interface": s(name, 64),
                "is_up": bool(iface.get("is_up")),
                "is_enabled": bool(iface.get("is_enabled")),
                "speed": iface.get("speed"),
                "description": s(iface.get("description"), 200),
                "mac_address": s(iface.get("mac_address"), 32),
            }
        )
    return out


def get_interfaces_ip(target: Any) -> list[dict]:
    """[READ] Per-interface IPv4/IPv6 addresses and prefix lengths."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_interfaces_ip", dev.get_interfaces_ip)
    out: list[dict] = []
    for name, families in (data or {}).items():
        for family, addrs in (families or {}).items():
            for addr, meta in (addrs or {}).items():
                out.append(
                    {
                        "interface": s(name, 64),
                        "family": s(family, 8),
                        "address": s(addr, 64),
                        "prefix_length": (meta or {}).get("prefix_length"),
                    }
                )
    return out


def get_bgp_neighbors(target: Any) -> list[dict]:
    """[READ] BGP neighbors per VRF: peer, remote AS, up state, prefix counts."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_bgp_neighbors", dev.get_bgp_neighbors)
    out: list[dict] = []
    for vrf, vrf_data in (data or {}).items():
        peers = (vrf_data or {}).get("peers", {}) or {}
        for peer, info in peers.items():
            ipv4 = ((info or {}).get("address_family", {}) or {}).get("ipv4", {}) or {}
            out.append(
                {
                    "vrf": s(vrf, 64),
                    "neighbor": s(peer, 64),
                    "remote_as": (info or {}).get("remote_as"),
                    "is_up": bool((info or {}).get("is_up")),
                    "is_enabled": bool((info or {}).get("is_enabled")),
                    "received_prefixes": ipv4.get("received_prefixes"),
                    "accepted_prefixes": ipv4.get("accepted_prefixes"),
                }
            )
    return out


def get_lldp_neighbors(target: Any) -> list[dict]:
    """[READ] LLDP neighbors: local port, remote hostname, remote port."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_lldp_neighbors", dev.get_lldp_neighbors)
    out: list[dict] = []
    for local_port, neighbors in (data or {}).items():
        for n in neighbors or []:
            out.append(
                {
                    "local_port": s(local_port, 64),
                    "remote_host": s((n or {}).get("hostname"), 128),
                    "remote_port": s((n or {}).get("port"), 64),
                }
            )
    return out


def get_arp_table(target: Any) -> list[dict]:
    """[READ] ARP table entries: interface, IP, MAC, age."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_arp_table", dev.get_arp_table)
    out: list[dict] = []
    for entry in data or []:
        out.append(
            {
                "interface": s((entry or {}).get("interface"), 64),
                "ip": s((entry or {}).get("ip"), 64),
                "mac": s((entry or {}).get("mac"), 32),
                "age": (entry or {}).get("age"),
            }
        )
    return out
