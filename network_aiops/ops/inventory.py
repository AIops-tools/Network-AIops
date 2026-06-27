"""Read-only L2/L3 inventory getters via NAPALM.

Covers interface counters, the MAC address table, VLANs, and a route lookup.
Device-returned text is sanitized; per-driver ``NotImplementedError`` becomes a
teaching ``NetworkApiError`` via ``getter()``.
"""

from __future__ import annotations

from typing import Any

from network_aiops.connection import device_session
from network_aiops.ops._shared import getter, s


def get_interfaces_counters(target: Any) -> list[dict]:
    """[READ] Per-interface traffic + error counters (octets, packets, errors, discards)."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_interfaces_counters", dev.get_interfaces_counters)
    out: list[dict] = []
    for name, c in (data or {}).items():
        c = c or {}
        out.append(
            {
                "interface": s(name, 64),
                "tx_octets": c.get("tx_octets"),
                "rx_octets": c.get("rx_octets"),
                "tx_unicast_packets": c.get("tx_unicast_packets"),
                "rx_unicast_packets": c.get("rx_unicast_packets"),
                "tx_errors": c.get("tx_errors"),
                "rx_errors": c.get("rx_errors"),
                "tx_discards": c.get("tx_discards"),
                "rx_discards": c.get("rx_discards"),
            }
        )
    return out


def get_mac_address_table(target: Any) -> list[dict]:
    """[READ] MAC address table: MAC, interface, VLAN, static/active flags."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_mac_address_table", dev.get_mac_address_table)
    out: list[dict] = []
    for entry in data or []:
        entry = entry or {}
        out.append(
            {
                "mac": s(entry.get("mac"), 32),
                "interface": s(entry.get("interface"), 64),
                "vlan": entry.get("vlan"),
                "static": bool(entry.get("static")),
                "active": bool(entry.get("active")),
                "moves": entry.get("moves"),
                "last_move": entry.get("last_move"),
            }
        )
    return out


def get_vlans(target: Any) -> list[dict]:
    """[READ] VLANs: id, name, and member interfaces (driver support varies)."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_vlans", dev.get_vlans)
    out: list[dict] = []
    for vlan_id, info in (data or {}).items():
        info = info or {}
        out.append(
            {
                "vlan_id": s(vlan_id, 16),
                "name": s(info.get("name"), 128),
                "interfaces": [s(i, 64) for i in (info.get("interfaces") or [])],
            }
        )
    return out


def get_route_to(target: Any, destination: str, protocol: str = "") -> list[dict]:
    """[READ] Routing-table lookup for a destination prefix (optionally by protocol)."""
    with device_session(target) as dev:
        data = getter(
            target.driver, "get_route_to", dev.get_route_to, destination, protocol
        )
    out: list[dict] = []
    for prefix, routes in (data or {}).items():
        for r in routes or []:
            r = r or {}
            out.append(
                {
                    "prefix": s(prefix, 64),
                    "protocol": s(r.get("protocol"), 32),
                    "current_active": bool(r.get("current_active")),
                    "next_hop": s(r.get("next_hop"), 64),
                    "outgoing_interface": s(r.get("outgoing_interface"), 64),
                    "preference": r.get("preference"),
                    "selected_next_hop": bool(r.get("selected_next_hop")),
                }
            )
    return out
