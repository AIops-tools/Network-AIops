"""NetBox source-of-truth MCP tools (read-only, optional).

Degrade gracefully: a clear ``NetworkApiError`` (surfaced via ``tool_errors``)
when NetBox is not configured, instead of an opaque traceback.
"""

from typing import Optional

from mcp_server._shared import _netbox, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import netbox_ops as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def netbox_list_devices(name: Optional[str] = None, limit: int = 50) -> dict:
    """[READ] List NetBox devices (name, role, site, status, primary IP).

    Requires a configured NetBox block. Use this to confirm intended state
    before pushing config to a device.

    Returns ``{"devices": [...], "returned": N, "limit": L, "truncated": bool}``.
    When ``truncated`` is true the estate is larger than what you were shown —
    re-run with a higher ``limit`` before concluding anything about coverage.

    Args:
        name: Optional name filter (contains match).
        limit: Maximum devices to return (default 50).
    """
    return ops.netbox_list_devices(_netbox(), limit=limit, name=name)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def netbox_get_device(name: str) -> dict:
    """[READ] Return a single NetBox device by exact name.

    Args:
        name: Exact NetBox device name (see netbox_list_devices).
    """
    return ops.netbox_get_device(_netbox(), name)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def netbox_device_interfaces(device: str, limit: int = 100) -> dict:
    """[READ] List a NetBox device's interfaces (name, type, enabled, description).

    The intended interface inventory from source-of-truth — compare against live
    device state (get_interfaces) to spot drift.

    Returns ``{"interfaces": [...], "returned": N, "limit": L, "truncated": bool}``.
    Do NOT report drift from a truncated list — re-run with a higher ``limit``.

    Args:
        device: Exact NetBox device name (see netbox_list_devices).
        limit: Maximum interfaces to return (default 100).
    """
    return ops.netbox_device_interfaces(_netbox(), device, limit=limit)
