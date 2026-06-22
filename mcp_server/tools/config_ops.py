"""Config MCP tools: backup + diff (read/dry-run), merge + replace + rollback (write).

Every tool is wrapped with ``@governed_tool`` (the network-aiops harness):
policy pre-check, budget/runaway guard, risk-tier gate, audit logging to
~/.network-aiops/audit.db, and undo-token recording. ``config_merge`` and
``config_replace`` capture the pre-change running config and pass an ``undo=``
lambda so the harness records a ``config_replace``-to-backup reversal (the
device must support config replace for the undo to apply). ``config_rollback``
records no undo.
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.ops import config_ops as ops


def _restore_undo(params: dict, result) -> Optional[dict]:
    """Build the inverse of a committed change: replace config back to the backup."""
    if not isinstance(result, dict) or "backup" not in result:
        return None
    return {
        "tool": "config_replace",
        "params": {"target": params.get("target"), "config_text": result["backup"]},
        "skill": "network-aiops",
        "note": (
            "Inverse: restore the captured pre-change running config via "
            "config_replace. The device must support config replace."
        ),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def config_backup(target: Optional[str] = None) -> dict:
    """[READ] Return the device running config (a note explains how to save it).

    Args:
        target: Device name from config; omit to use the default device.
    """
    return ops.config_backup(_target(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def config_diff(
    config_text: str, replace: bool = False, target: Optional[str] = None
) -> dict:
    """[READ] DRY-RUN: stage a candidate, return the diff, then discard it.

    Nothing is committed. This is the dry-run primitive for previewing a change.

    Args:
        config_text: The configuration snippet (merge) or full config (replace).
        replace: True to diff as a full-config replacement; False (default) to merge.
        target: Device name from config.
    """
    return ops.config_diff(_target(target), config_text, replace=replace)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_restore_undo)
@tool_errors("dict")
def config_merge(config_text: str, target: Optional[str] = None) -> dict:
    """[WRITE] Merge a config snippet and commit. Captures running config for undo.

    Returns ``diff`` (what changed) and ``backup`` (pre-change running config).
    The recorded undo restores ``backup`` via config_replace.

    Args:
        config_text: The configuration snippet to merge.
        target: Device name from config.
    """
    return ops.config_merge(_target(target), config_text)


@mcp.tool()
@governed_tool(risk_level="high", undo=_restore_undo)
@tool_errors("dict")
def config_replace(config_text: str, target: Optional[str] = None) -> dict:
    """[WRITE] Replace the full config and commit. HIGH RISK. Captures running for undo.

    Returns ``diff`` and ``backup``. The recorded undo replaces the config back
    to ``backup`` (the device must support config replace).

    Args:
        config_text: The full replacement configuration.
        target: Device name from config.
    """
    return ops.config_replace(_target(target), config_text)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def config_rollback(target: Optional[str] = None) -> dict:
    """[WRITE] Revert the last committed change via NAPALM rollback(). No undo.

    Device support varies (rollback depth is platform-dependent).

    Args:
        target: Device name from config.
    """
    return ops.config_rollback(_target(target))
