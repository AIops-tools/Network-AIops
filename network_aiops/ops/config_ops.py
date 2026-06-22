"""Configuration operations: backup, diff (dry-run), merge, replace, rollback.

NAPALM config workflow:
  - ``get_config(retrieve="running")`` reads the running config (backup).
  - ``load_merge_candidate`` / ``load_replace_candidate`` stage a candidate.
  - ``compare_config()`` returns the diff WITHOUT committing.
  - ``commit_config()`` applies the staged candidate.
  - ``discard_config()`` throws the candidate away (used by the dry-run diff).
  - ``rollback()`` reverts the last commit (device support varies).

All device-returned text is sanitized. Write ops capture the pre-change running
config first and return it as ``backup`` so the harness can record an undo that
restores it via ``config_replace``.
"""

from __future__ import annotations

from typing import Any

from network_aiops.ops._shared import s

_MAX_CONFIG = 200_000


def _running_config(dev: Any) -> str:
    """Read the running config as a string."""
    cfg = dev.get_config(retrieve="running")
    return cfg.get("running", "") if isinstance(cfg, dict) else str(cfg)


def config_backup(target: Any) -> dict:
    """[READ] Return the device running config. Save to a file with the CLI '-o'."""
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        running = _running_config(dev)
    return {
        "name": s(target.name, 128),
        "config": sanitize_config(running),
        "note": "Running config. Use the CLI '-o <path>' flag to save it to a file.",
    }


def config_diff(target: Any, config_text: str, replace: bool = False) -> dict:
    """[READ / DRY-RUN] Stage a candidate, return the diff, then discard it.

    This is the dry-run primitive: nothing is committed. ``replace=False`` uses
    a merge candidate (additive); ``replace=True`` uses a replace candidate
    (the diff reflects a full-config replacement).
    """
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        if replace:
            dev.load_replace_candidate(config=config_text)
        else:
            dev.load_merge_candidate(config=config_text)
        try:
            diff = dev.compare_config()
        finally:
            dev.discard_config()
    return {
        "name": s(target.name, 128),
        "mode": "replace" if replace else "merge",
        "diff": sanitize_config(diff),
        "committed": False,
        "note": "Dry-run only — no changes were committed.",
    }


def config_merge(target: Any, config_text: str) -> dict:
    """[WRITE] Merge config snippet and commit. Captures running config for undo.

    Returns ``diff`` (what changed) and ``backup`` (pre-change running config).
    """
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        backup = _running_config(dev)
        dev.load_merge_candidate(config=config_text)
        diff = dev.compare_config()
        dev.commit_config()
    return {
        "name": s(target.name, 128),
        "action": "merged",
        "committed": True,
        "diff": sanitize_config(diff),
        "backup": sanitize_config(backup),
    }


def config_replace(target: Any, config_text: str) -> dict:
    """[WRITE / HIGH] Replace the full config and commit. Captures running for undo.

    Returns ``diff`` and ``backup`` (pre-change running config). The undo is to
    replace the device config back to ``backup`` — the device must support
    config replace for the undo to apply.
    """
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        backup = _running_config(dev)
        dev.load_replace_candidate(config=config_text)
        diff = dev.compare_config()
        dev.commit_config()
    return {
        "name": s(target.name, 128),
        "action": "replaced",
        "committed": True,
        "diff": sanitize_config(diff),
        "backup": sanitize_config(backup),
    }


def config_rollback(target: Any) -> dict:
    """[WRITE] Revert the last committed change via NAPALM rollback().

    Device support varies (some platforms keep only a single rollback point).
    No undo is recorded for a rollback.
    """
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        dev.rollback()
    return {
        "name": s(target.name, 128),
        "action": "rolled_back",
        "committed": True,
        "note": "Reverted the last commit. Rollback depth is device-dependent.",
    }


def sanitize_config(text: str | None) -> str:
    """Sanitize a (possibly large) config/diff blob: strip control chars, bound size."""
    return s(text, _MAX_CONFIG)
