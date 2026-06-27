"""Read-only neighbor-detail MCP tools (BGP / LLDP).

Every tool is wrapped with ``@governed_tool`` (the network-aiops harness):
policy pre-check, budget/runaway guard, risk-tier gate, and audit logging to
~/.network-aiops/audit.db. These are all READ tools (no undo).
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import neighbors as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_bgp_neighbors_detail(target: Optional[str] = None) -> list:
    """[READ] Detailed BGP neighbors per VRF: state, router id, AS, prefix stats.

    Args:
        target: Device name from config; omit to use the default device.
    """
    return ops.get_bgp_neighbors_detail(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_lldp_neighbors_detail(target: Optional[str] = None) -> list:
    """[READ] Detailed LLDP neighbors: chassis id, system name/description, capabilities.

    Args:
        target: Device name from config.
    """
    return ops.get_lldp_neighbors_detail(_target(target))
