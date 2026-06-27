"""Read-only neighbor-detail getters (BGP / LLDP) via NAPALM.

These are the verbose counterparts to the summaries in ``facts.py``. As with
all ops, device-returned text is sanitized, per-driver ``NotImplementedError``
becomes a teaching ``NetworkApiError`` via ``getter()``, and each call opens a
short-lived NAPALM session and closes it.
"""

from __future__ import annotations

from typing import Any

from network_aiops.connection import device_session
from network_aiops.ops._shared import getter, s


def get_bgp_neighbors_detail(target: Any) -> list[dict]:
    """[READ] Detailed BGP neighbors per VRF: state, router id, AS, prefix stats."""
    with device_session(target) as dev:
        data = getter(
            target.driver, "get_bgp_neighbors_detail", dev.get_bgp_neighbors_detail
        )
    out: list[dict] = []
    for vrf, peers in (data or {}).items():
        for peer_ip, entries in (peers or {}).items():
            for info in entries or []:
                info = info or {}
                out.append(
                    {
                        "vrf": s(vrf, 64),
                        "neighbor": s(peer_ip, 64),
                        "remote_as": info.get("remote_as"),
                        "local_as": info.get("local_as"),
                        "router_id": s(info.get("remote_router_id"), 64),
                        "up": bool(info.get("up")),
                        "connection_state": s(info.get("connection_state"), 32),
                        "received_prefixes": info.get("received_prefix_count"),
                        "accepted_prefixes": info.get("accepted_prefix_count"),
                        "advertised_prefixes": info.get("advertised_prefix_count"),
                    }
                )
    return out


def get_lldp_neighbors_detail(target: Any) -> list[dict]:
    """[READ] Detailed LLDP neighbors: chassis id, system name/description, capabilities."""
    with device_session(target) as dev:
        data = getter(
            target.driver, "get_lldp_neighbors_detail", dev.get_lldp_neighbors_detail
        )
    out: list[dict] = []
    for local_port, neighbors in (data or {}).items():
        for n in neighbors or []:
            n = n or {}
            out.append(
                {
                    "local_port": s(local_port, 64),
                    "remote_chassis_id": s(n.get("remote_chassis_id"), 64),
                    "remote_system_name": s(n.get("remote_system_name"), 128),
                    "remote_port": s(n.get("remote_port"), 64),
                    "remote_port_description": s(n.get("remote_port_description"), 200),
                    "remote_system_description": s(n.get("remote_system_description"), 200),
                    "remote_system_capab": [s(c, 32) for c in (n.get("remote_system_capab") or [])],
                    "remote_system_enable_capab": [
                        s(c, 32) for c in (n.get("remote_system_enable_capab") or [])
                    ],
                }
            )
    return out
