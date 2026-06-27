"""Aggregated device-health MCP tool.

Wrapped with ``@governed_tool`` (the network-aiops harness). READ tier — it only
reads facts, interface state, and environment.
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import health as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def device_health(target: Optional[str] = None) -> dict:
    """[READ] Aggregated health: facts + interface up/down counts + environment.

    Resilient to drivers lacking get_environment (that section becomes a note).
    Returns a 'healthy' flag and an 'issues' list summarising attention points.

    Args:
        target: Device name from config; omit to use the default device.
    """
    return ops.device_health(_target(target))
