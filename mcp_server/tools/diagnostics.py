"""Diagnostics / RCA MCP tools: interface health and BGP neighbor health.

Read-only signature analyses (risk_level="low"). Each tool collects the relevant
NAPALM getter output via the ``network_aiops`` ops layer and hands it to a pure
analysis function in ``network_aiops.ops.diagnostics`` — so the heuristics stay
unit-testable without a live device, and the device collection stays here where
the connection is.
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import diagnostics as diag
from network_aiops.ops import facts, inventory


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def interface_health_rca(target: Optional[str] = None) -> dict:
    """[READ] Flag admin-up/oper-down, erroring, discarding, or flapping interfaces.

    Pulls get_interfaces + get_interfaces_counters and reports worst-first
    findings — each citing the measured number (error/discard count, last-flap
    seconds) that tripped it, with a cause and a concrete action.

    Args:
        target: Device name from config; omit to use the default device.
    """
    t = _target(target)
    interfaces = facts.get_interfaces(t)
    counters = inventory.get_interfaces_counters(t)
    return diag.interface_health_findings(interfaces, counters)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def bgp_neighbor_rca(target: Optional[str] = None) -> dict:
    """[READ] Flag BGP neighbors that are down, shut, recently reset, or route-less.

    Pulls get_bgp_neighbors and reports worst-first findings, each citing the
    session state (is_up / is_enabled) or uptime, with a cause and an action
    (check peer reachability / ACL / MD5 auth).

    Args:
        target: Device name from config; omit to use the default device.
    """
    return diag.bgp_neighbor_findings(facts.get_bgp_neighbors(_target(target)))
