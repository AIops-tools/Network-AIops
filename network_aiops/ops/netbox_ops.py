"""Optional NetBox source-of-truth lookups (read-only).

Degrades gracefully: ``connection.netbox_api`` raises a teaching
``NetworkApiError`` when NetBox is not configured. All NetBox-returned text is
sanitized. Returns are high-signal summaries.
"""

from __future__ import annotations

from typing import Any

from network_aiops.governance import opt_str


def _device_summary(d: Any) -> dict:
    return {
        "name": opt_str(getattr(d, "name", None), 128),
        "role": opt_str(getattr(getattr(d, "role", None), "name", None), 64),
        "site": opt_str(getattr(getattr(d, "site", None), "name", None), 64),
        "status": opt_str(getattr(getattr(d, "status", None), "value", None), 32),
        "primary_ip": opt_str(getattr(getattr(d, "primary_ip", None), "address", None), 64),
    }


def netbox_list_devices(api: Any, limit: int = 50, name: str | None = None) -> dict:
    """[READ] List NetBox devices (name, role, site, status, primary IP).

    Supports an optional ``name`` filter and a default page ``limit`` of 50.

    Returns an envelope rather than a bare list::

        {"devices": [...], "returned": 50, "limit": 50, "truncated": true}

    so a truncated read announces itself. A bare list cannot say "there is
    more" — the consumer has to infer it from the length happening to equal the
    limit, and a smaller local model faced with a capped result tends to report
    the partial inventory as if it were the whole estate. One extra device is
    requested so ``truncated`` is *measured* rather than guessed.
    """
    requested = max(1, int(limit))
    kwargs: dict[str, Any] = {"limit": requested + 1}
    if name:
        kwargs["name__ic"] = name
    raw = list(api.dcim.devices.filter(**kwargs))
    truncated = len(raw) > requested
    devices = [_device_summary(d) for d in raw[:requested]]
    return {
        "devices": devices,
        "returned": len(devices),
        "limit": requested,
        "truncated": truncated,
    }


def netbox_device_interfaces(api: Any, device: str, limit: int = 100) -> dict:
    """[READ] List interfaces of a NetBox device (name, type, enabled, description).

    ``device`` is the exact NetBox device name. Returns the intended interface
    inventory from source-of-truth — handy to compare against live device state.

    Returns an envelope::

        {"interfaces": [...], "returned": 100, "limit": 100, "truncated": true}

    One extra interface is requested so ``truncated`` is measured, not guessed.
    A silently-capped interface list is the worst possible input to a drift
    comparison against the live device: the missing interfaces would read as
    "not in source of truth".
    """
    requested = max(1, int(limit))
    raw = list(api.dcim.interfaces.filter(device=device, limit=requested + 1))
    truncated = len(raw) > requested
    out: list[dict] = []
    for i in raw[:requested]:
        out.append(
            {
                "name": opt_str(getattr(i, "name", None), 64),
                "type": opt_str(getattr(getattr(i, "type", None), "value", None), 64),
                "enabled": bool(getattr(i, "enabled", False)),
                "description": opt_str(getattr(i, "description", None), 200),
                "mac_address": opt_str(getattr(i, "mac_address", None), 32),
            }
        )
    return {
        "interfaces": out,
        "returned": len(out),
        "limit": requested,
        "truncated": truncated,
    }


def netbox_get_device(api: Any, name: str) -> dict:
    """[READ] Return a single NetBox device by exact name."""
    device = api.dcim.devices.get(name=name)
    if device is None:
        return {
            "error": f"NetBox device '{name}' not found. Use netbox_list_devices "
            f"to see available names."
        }
    summary = _device_summary(device)
    summary["device_type"] = opt_str(
        getattr(getattr(device, "device_type", None), "model", None), 128
    )
    summary["serial"] = opt_str(getattr(device, "serial", None), 128)
    return summary
