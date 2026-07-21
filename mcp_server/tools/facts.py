"""Read-only device facts MCP tools (NAPALM getters).

Every tool is wrapped with ``@governed_tool`` (the network-aiops harness):
budget/runaway guard, risk-tier tagging, and audit logging to
~/.network-aiops/audit.db. These are all READ tools (no undo).
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import facts as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def device_facts(target: Optional[str] = None) -> dict:
    """[READ] Core device facts: hostname, vendor, model, OS version, serial, uptime.

    Also returns the interface name list. Use get_interfaces for per-interface
    state/speed.

    Args:
        target: Device name from config; omit to use the default device.
    """
    return ops.device_facts(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_interfaces(target: Optional[str] = None) -> list:
    """[READ] Interfaces with up/down state, enabled flag, speed, and description.

    Args:
        target: Device name from config.
    """
    return ops.get_interfaces(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_interfaces_ip(target: Optional[str] = None) -> list:
    """[READ] Per-interface IPv4/IPv6 addresses and prefix lengths.

    Args:
        target: Device name from config.
    """
    return ops.get_interfaces_ip(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_bgp_neighbors(target: Optional[str] = None) -> list:
    """[READ] BGP neighbors per VRF: peer, remote AS, up state, prefix counts.

    Args:
        target: Device name from config.
    """
    return ops.get_bgp_neighbors(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_lldp_neighbors(target: Optional[str] = None) -> list:
    """[READ] LLDP neighbors: local port, remote hostname, remote port.

    Args:
        target: Device name from config.
    """
    return ops.get_lldp_neighbors(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_arp_table(target: Optional[str] = None) -> list:
    """[READ] ARP table entries: interface, IP, MAC, age.

    Args:
        target: Device name from config.
    """
    return ops.get_arp_table(_target(target))
