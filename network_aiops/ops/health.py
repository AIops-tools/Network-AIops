"""Aggregated device health summary.

``device_health`` opens a single NAPALM session and combines facts, interface
up/down counts, and (where supported) the hardware environment into one
high-signal status dict. Each sub-getter is tolerated independently: a getter
the driver does not implement is reported as unavailable rather than failing the
whole summary.
"""

from __future__ import annotations

from typing import Any

from network_aiops.connection import NetworkApiError, device_session
from network_aiops.governance import opt_str
from network_aiops.ops._shared import getter, s


def _interface_counts(dev: Any, driver: str) -> dict:
    data = getter(driver, "get_interfaces", dev.get_interfaces) or {}
    total = len(data)
    up = sum(1 for i in data.values() if (i or {}).get("is_up"))
    enabled_down = sum(
        1 for i in data.values() if (i or {}).get("is_enabled") and not (i or {}).get("is_up")
    )
    return {
        "total": total,
        "up": up,
        "down": total - up,
        "enabled_but_down": enabled_down,  # likely problems worth attention
    }


def _environment_summary(dev: Any, driver: str) -> dict:
    env = getter(driver, "get_environment", dev.get_environment) or {}
    temps = [
        (v or {}).get("temperature")
        for v in (env.get("temperature") or {}).values()
        if (v or {}).get("temperature") is not None
    ]
    fans_ok = all(bool((v or {}).get("status")) for v in (env.get("fans") or {}).values())
    power_ok = all(bool((v or {}).get("status")) for v in (env.get("power") or {}).values())
    temp_alert = any(
        (v or {}).get("is_alert") or (v or {}).get("is_critical")
        for v in (env.get("temperature") or {}).values()
    )
    mem = env.get("memory") or {}
    cpus = [(v or {}).get("%usage") for v in (env.get("cpu") or {}).values()]
    return {
        "fans_ok": fans_ok,
        "power_ok": power_ok,
        "temperature_alert": bool(temp_alert),
        "max_temperature": max(temps) if temps else None,
        "max_cpu_usage": max([c for c in cpus if c is not None], default=None),
        "available_ram": mem.get("available_ram"),
        "used_ram": mem.get("used_ram"),
    }


def device_health(target: Any) -> dict:
    """[READ] Aggregated health: facts + interface up/down counts + environment.

    Resilient to drivers that lack ``get_environment``: that section becomes a
    note instead of failing the whole summary.
    """
    notes: list[str] = []
    with device_session(target) as dev:
        facts = getter(target.driver, "get_facts", dev.get_facts) or {}
        interfaces = _interface_counts(dev, target.driver)
        try:
            environment = _environment_summary(dev, target.driver)
        except NetworkApiError as exc:
            environment = None
            notes.append(s(str(exc), 200))

    issues: list[str] = []
    if interfaces["enabled_but_down"]:
        issues.append(f"{interfaces['enabled_but_down']} enabled interface(s) are down")
    if environment:
        if not environment["fans_ok"]:
            issues.append("one or more fans are not OK")
        if not environment["power_ok"]:
            issues.append("one or more power supplies are not OK")
        if environment["temperature_alert"]:
            issues.append("a temperature sensor is in alert/critical state")

    return {
        "name": s(target.name, 128),
        "hostname": opt_str(facts.get("hostname"), 128),
        "model": opt_str(facts.get("model"), 128),
        "os_version": opt_str(facts.get("os_version"), 200),
        "uptime_seconds": int(facts.get("uptime") or 0),
        "interfaces": interfaces,
        "environment": environment,
        "healthy": not issues,
        "issues": issues,
        "notes": notes,
    }
