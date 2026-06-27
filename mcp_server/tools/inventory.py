"""Read-only L2/L3 inventory MCP tools (counters / MAC table / VLANs / route lookup).

Every tool is wrapped with ``@governed_tool`` (the network-aiops harness). All
READ tier (no undo).
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import inventory as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_interfaces_counters(target: Optional[str] = None) -> list:
    """[READ] Per-interface traffic + error counters (octets, packets, errors, discards).

    Args:
        target: Device name from config.
    """
    return ops.get_interfaces_counters(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_mac_address_table(target: Optional[str] = None) -> list:
    """[READ] MAC address table: MAC, interface, VLAN, static/active flags.

    Args:
        target: Device name from config.
    """
    return ops.get_mac_address_table(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_vlans(target: Optional[str] = None) -> list:
    """[READ] VLANs: id, name, and member interfaces (driver support varies).

    Args:
        target: Device name from config.
    """
    return ops.get_vlans(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_route_to(
    destination: str, protocol: str = "", target: Optional[str] = None
) -> list:
    """[READ] Routing-table lookup for a destination prefix (optionally by protocol).

    Args:
        destination: The destination prefix to look up (e.g. 10.0.0.0/24).
        protocol: Optional protocol filter (e.g. bgp, ospf, static).
        target: Device name from config.
    """
    return ops.get_route_to(_target(target), destination, protocol)
