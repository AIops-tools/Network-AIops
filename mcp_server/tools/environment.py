"""Read-only platform/environment MCP tools.

Hardware environment, optics, NTP, local users, SNMP info, and VRFs. Every tool
is wrapped with ``@governed_tool`` (the network-aiops harness). All READ tier.
Secrets (user password hashes, SNMP community strings) are never returned.
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import environment as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def get_environment(target: Optional[str] = None) -> dict:
    """[READ] Hardware environment: fans, temperature, power, CPU, memory.

    Args:
        target: Device name from config; omit to use the default device.
    """
    return ops.get_environment(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_optics(target: Optional[str] = None) -> list:
    """[READ] Optical transceiver levels per interface/channel (rx/tx power, bias).

    Args:
        target: Device name from config.
    """
    return ops.get_optics(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_ntp_servers(target: Optional[str] = None) -> list:
    """[READ] Configured NTP servers.

    Args:
        target: Device name from config.
    """
    return ops.get_ntp_servers(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_ntp_stats(target: Optional[str] = None) -> list:
    """[READ] NTP peer synchronization stats (stratum, offset, jitter, reachability).

    Args:
        target: Device name from config.
    """
    return ops.get_ntp_stats(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_users(target: Optional[str] = None) -> list:
    """[READ] Local users and privilege levels. Password hashes are NOT returned.

    Args:
        target: Device name from config.
    """
    return ops.get_users(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def get_snmp_information(target: Optional[str] = None) -> dict:
    """[READ] SNMP metadata: chassis id, contact, location. Community strings redacted.

    Args:
        target: Device name from config.
    """
    return ops.get_snmp_information(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def get_network_instances(target: Optional[str] = None) -> list:
    """[READ] Network instances (VRFs): name, type, state, member interfaces.

    Args:
        target: Device name from config.
    """
    return ops.get_network_instances(_target(target))
