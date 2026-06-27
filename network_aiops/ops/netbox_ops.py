"""Optional NetBox source-of-truth lookups (read-only).

Degrades gracefully: ``connection.netbox_api`` raises a teaching
``NetworkApiError`` when NetBox is not configured. All NetBox-returned text is
sanitized. Returns are high-signal summaries.
"""

from __future__ import annotations

from typing import Any

from network_aiops.ops._shared import s


def _device_summary(d: Any) -> dict:
    return {
        "name": s(getattr(d, "name", ""), 128),
        "role": s(getattr(getattr(d, "role", None), "name", ""), 64),
        "site": s(getattr(getattr(d, "site", None), "name", ""), 64),
        "status": s(getattr(getattr(d, "status", None), "value", ""), 32),
        "primary_ip": s(getattr(getattr(d, "primary_ip", None), "address", ""), 64),
    }


def netbox_list_devices(api: Any, limit: int = 50, name: str | None = None) -> list[dict]:
    """[READ] List NetBox devices (name, role, site, status, primary IP).

    Supports an optional ``name`` filter and a default page ``limit`` of 50.
    """
    kwargs: dict[str, Any] = {"limit": max(1, limit)}
    if name:
        kwargs["name__ic"] = name
    devices = api.dcim.devices.filter(**kwargs)
    return [_device_summary(d) for d in devices]


def netbox_device_interfaces(api: Any, device: str, limit: int = 100) -> list[dict]:
    """[READ] List interfaces of a NetBox device (name, type, enabled, description).

    ``device`` is the exact NetBox device name. Returns the intended interface
    inventory from source-of-truth — handy to compare against live device state.
    """
    interfaces = api.dcim.interfaces.filter(device=device, limit=max(1, limit))
    out: list[dict] = []
    for i in interfaces:
        out.append(
            {
                "name": s(getattr(i, "name", ""), 64),
                "type": s(getattr(getattr(i, "type", None), "value", ""), 64),
                "enabled": bool(getattr(i, "enabled", False)),
                "description": s(getattr(i, "description", ""), 200),
                "mac_address": s(getattr(i, "mac_address", "") or "", 32),
            }
        )
    return out


def netbox_get_device(api: Any, name: str) -> dict:
    """[READ] Return a single NetBox device by exact name."""
    device = api.dcim.devices.get(name=name)
    if device is None:
        return {
            "error": f"NetBox device '{name}' not found. Use netbox_list_devices "
            f"to see available names."
        }
    summary = _device_summary(device)
    summary["device_type"] = s(
        getattr(getattr(device, "device_type", None), "model", ""), 128
    )
    summary["serial"] = s(getattr(device, "serial", ""), 128)
    return summary
