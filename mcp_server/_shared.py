"""Shared MCP server primitives: the FastMCP instance, manager helper,
error sanitisation, and the ``@tool_errors`` decorator.

Tool modules under ``mcp_server/tools/`` import ``mcp`` from here and register
their ``@mcp.tool()`` functions onto it. ``mcp_server/server.py`` then imports
those modules and runs the server.

Keep ``Optional[X]`` (never PEP 604 ``X | None``) in any FastMCP-reflected
tool signature — on older mcp/pydantic the union eval'd to ``types.UnionType``
crashes FastMCP's ``issubclass`` check.
"""

import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from network_aiops.config import load_config
from network_aiops.connection import ConnectionManager, NetworkApiError
from network_aiops.governance import sanitize

logger = logging.getLogger(__name__)

_DOCTOR_HINT = "Run 'network-aiops doctor' to verify device config and reachability."

_SUPPORTED = "ios, nxos, nxos_ssh, iosxr, eos, junos"


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only."""
    logger.error("Tool %s failed", tool, exc_info=True)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        NetworkApiError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def tool_errors(shape: str = "dict") -> Callable:
    """Wrap a tool body in the canonical try/except → ``_safe_error`` pattern.

    Place this *between* ``@governed_tool`` and the function so the audit
    decorator and FastMCP still see the original signature.
    """

    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — sanitised below
                msg = _safe_error(e, name)
                if shape == "list":
                    return [{"error": msg, "hint": _DOCTOR_HINT}]
                if shape == "str":
                    return f"Error: {msg} {_DOCTOR_HINT}"
                return {"error": msg, "hint": _DOCTOR_HINT}

        return wrapper

    return decorator


mcp = FastMCP(
    "network-aiops",
    instructions=(
        "Governed multi-vendor network device operations over NAPALM. "
        f"Officially supported drivers: {_SUPPORTED} (Cisco IOS/IOS-XE, Nexus "
        "NX-OS, IOS-XR, Arista EOS, Juniper Junos). Read tools: device facts, "
        "interfaces (+ counters / IP), BGP & LLDP neighbors (summary + detail), "
        "ARP & MAC tables, VLANs, route lookup, environment (fans/temp/power/"
        "CPU/mem), optics, NTP, users, SNMP info, VRFs, an aggregated device_health, "
        "read-only RCA diagnostics (interface_health_rca, bgp_neighbor_rca — each "
        "finding cites the measured value, worst-first), "
        "config backup, and config diff (dry-run). Write tools: config merge, "
        "config replace, config rollback. An optional NetBox block adds "
        "source-of-truth device + interface lookups. Many getters are not "
        "implemented by every NAPALM driver — unsupported ones return a clear "
        "'not supported by the <driver> driver' message rather than crashing. "
        "Credentials (device passwords + NetBox token) live in an encrypted store "
        "unlocked via NETWORK_AIOPS_MASTER_PASSWORD. A 'target' selects a device "
        "from config. Every tool runs "
        "through the network-aiops governance harness (audit / budget / risk-tier "
        "/ undo). Need another platform (Nokia SR OS, Huawei VRP) or action? "
        "Request it via a GitHub issue or PR."
    ),
)

_conn_mgr: Optional[ConnectionManager] = None


def _manager() -> ConnectionManager:
    """Return the connection manager, lazily initialising it from config."""
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        config_path_str = os.environ.get("NETWORK_AIOPS_CONFIG")
        config_path = Path(config_path_str) if config_path_str else None
        _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr


def _target(name: Optional[str] = None) -> Any:
    """Resolve a device target by name (or the default device)."""
    return _manager().target(name)


def _netbox() -> Any:
    """Return a NetBox client (raises a teaching NetworkApiError if unconfigured)."""
    return _manager().netbox()
