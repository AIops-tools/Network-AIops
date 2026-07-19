"""Read-only platform/environment getters via NAPALM.

Covers hardware environment (fans/temp/power/CPU/memory), optical transceivers,
NTP servers/stats, local users, SNMP information, and network instances (VRFs).
Secrets are NEVER returned: user password hashes and SNMP community strings are
redacted to booleans. Per-driver ``NotImplementedError`` becomes a teaching
``NetworkApiError`` via ``getter()``.
"""

from __future__ import annotations

from typing import Any

from network_aiops.connection import device_session
from network_aiops.governance import opt_str
from network_aiops.ops._shared import getter, s


def get_environment(target: Any) -> dict:
    """[READ] Hardware environment: fans, temperature, power, CPU, memory."""
    with device_session(target) as dev:
        env = getter(target.driver, "get_environment", dev.get_environment)
    env = env or {}
    fans = {
        s(k, 64): {"status": bool((v or {}).get("status"))}
        for k, v in (env.get("fans") or {}).items()
    }
    temps = {
        s(k, 64): {
            "temperature": (v or {}).get("temperature"),
            "is_alert": bool((v or {}).get("is_alert")),
            "is_critical": bool((v or {}).get("is_critical")),
        }
        for k, v in (env.get("temperature") or {}).items()
    }
    power = {
        s(k, 64): {
            "status": bool((v or {}).get("status")),
            "capacity": (v or {}).get("capacity"),
            "output": (v or {}).get("output"),
        }
        for k, v in (env.get("power") or {}).items()
    }
    cpu = {s(k, 32): {"usage": (v or {}).get("%usage")} for k, v in (env.get("cpu") or {}).items()}
    memory = env.get("memory") or {}
    return {
        "name": s(target.name, 128),
        "fans": fans,
        "temperature": temps,
        "power": power,
        "cpu": cpu,
        "memory": {
            "available_ram": memory.get("available_ram"),
            "used_ram": memory.get("used_ram"),
        },
    }


def get_optics(target: Any) -> list[dict]:
    """[READ] Optical transceiver levels per interface/channel (rx/tx power, bias)."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_optics", dev.get_optics)
    out: list[dict] = []
    for iface, info in (data or {}).items():
        channels = ((info or {}).get("physical_channels", {}) or {}).get("channel", []) or []
        for ch in channels:
            ch = ch or {}
            state = ch.get("state", {}) or {}
            bias = (state.get("laser_bias_current", {}) or {}).get("instant")
            out.append(
                {
                    "interface": s(iface, 64),
                    "index": ch.get("index"),
                    "input_power": (state.get("input_power", {}) or {}).get("instant"),
                    "output_power": (state.get("output_power", {}) or {}).get("instant"),
                    "laser_bias_current": bias,
                }
            )
    return out


def get_ntp_servers(target: Any) -> list[str]:
    """[READ] Configured NTP servers."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_ntp_servers", dev.get_ntp_servers)
    return [s(server, 64) for server in (data or {})]


def get_ntp_stats(target: Any) -> list[dict]:
    """[READ] NTP peer synchronization stats (stratum, offset, jitter, reachability)."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_ntp_stats", dev.get_ntp_stats)
    out: list[dict] = []
    for entry in data or []:
        entry = entry or {}
        out.append(
            {
                "remote": opt_str(entry.get("remote"), 64),
                "synchronized": bool(entry.get("synchronized")),
                "stratum": entry.get("stratum"),
                "type": opt_str(entry.get("type"), 16),
                "reachability": entry.get("reachability"),
                "delay": entry.get("delay"),
                "offset": entry.get("offset"),
                "jitter": entry.get("jitter"),
            }
        )
    return out


def get_users(target: Any) -> list[dict]:
    """[READ] Local users and privilege levels. Password hashes are NOT returned."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_users", dev.get_users)
    out: list[dict] = []
    for username, info in (data or {}).items():
        info = info or {}
        out.append(
            {
                "username": s(username, 64),
                "level": info.get("level"),
                "has_password": bool(info.get("password")),
                "ssh_key_count": len(info.get("sshkeys") or []),
            }
        )
    return out


def get_snmp_information(target: Any) -> dict:
    """[READ] SNMP metadata: chassis id, contact, location. Community strings redacted."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_snmp_information", dev.get_snmp_information)
    data = data or {}
    communities = data.get("community") or {}
    return {
        "name": s(target.name, 128),
        "chassis_id": opt_str(data.get("chassis_id"), 128),
        "contact": opt_str(data.get("contact"), 200),
        "location": opt_str(data.get("location"), 200),
        "community_count": len(communities),  # values redacted (secrets)
    }


def get_network_instances(target: Any) -> list[dict]:
    """[READ] Network instances (VRFs): name, type, state, member interfaces."""
    with device_session(target) as dev:
        data = getter(target.driver, "get_network_instances", dev.get_network_instances)
    out: list[dict] = []
    for name, info in (data or {}).items():
        info = info or {}
        state = info.get("state", {}) or {}
        interfaces = (info.get("interfaces", {}) or {}).get("interface", {}) or {}
        out.append(
            {
                "name": s(name, 64),
                "type": opt_str(state.get("type") or info.get("type"), 64),
                "route_distinguisher": opt_str(state.get("route_distinguisher"), 64),
                "interfaces": [s(i, 64) for i in interfaces],
            }
        )
    return out
