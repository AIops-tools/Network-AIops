"""Config MCP tools: backup + diff (read/dry-run), merge/replace/confirm/rollback (write).

Every tool is wrapped with ``@governed_tool`` (the network-aiops harness):
budget/runaway guard, risk-tier tagging, audit logging to
~/.network-aiops/audit.db, and undo-token recording.

``config_merge`` and ``config_replace`` commit under a device-side revert timer
(``revert_in``, default 300s) and capture the pre-change running config for the
undo. The RAW backup travels to the harness through ``capture_prior_state``,
NOT through the result — a running config carries credential hashes, SNMP
communities and PSKs, and a tool result goes straight into an agent transcript.
``_restore_undo`` reads it back from that stash and builds a
``config_replace``-to-backup inverse. ``config_rollback`` records no undo.

``config_backup`` cannot withhold the config — returning it is the tool's
contract — so it masks credential VALUES instead and takes ``include_secrets``
to opt back in. Every ``diff`` gets the same treatment, because a diff that adds
``snmp-server community X`` carries X. The masking is always reported in a
``redaction`` block: a transformation the caller cannot detect is worse than
none, since it silently changes what "I read the config" means.
"""

from typing import Optional

from mcp_server._shared import _target, mcp, tool_errors
from network_aiops.governance import governed_tool
from network_aiops.governance.outcome import take_prior_state
from network_aiops.ops import config_ops as ops
from network_aiops.ops.config_ops import DEFAULT_REVERT_IN


def _restore_undo(params: dict, result) -> Optional[dict]:
    """Build the inverse of a committed change: replace config back to the backup.

    The pre-change config is read from the harness' prior-state stash (the write
    put it there before committing) rather than from ``result``, which carries
    only a digest. On the lost-response path the harness has already consumed
    the stash and hands it over inside ``result["priorState"]``.
    """
    prior = result.get("priorState") if isinstance(result, dict) else None
    if not isinstance(prior, dict):
        prior = take_prior_state() or {}
    running = prior.get("running")
    if not isinstance(running, str) or not running.strip():
        return None
    return {
        "tool": "config_replace",
        "params": {
            "target": params.get("target"),
            "config_text": running,
            # The restore must NOT sit under a revert timer of its own: nobody
            # confirms a rollback, and an auto-revert would put the broken
            # config straight back.
            "revert_in": 0,
        },
        "skill": "network-aiops",
        "note": (
            "Inverse: restore the captured pre-change running config via "
            "config_replace (no revert timer — a rollback must be permanent). "
            "The device must support config replace."
        ),
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def config_backup(include_secrets: bool = False, target: Optional[str] = None) -> dict:
    """[READ] Return the device running config, credential values masked by default.

    Password/secret hashes, SNMP communities, SNMPv3 auth+priv keys, IKE
    pre-shared keys and RADIUS/TACACS/keychain keys are replaced with
    "<redacted>"; every other line comes back untouched, so interface, routing
    and policy config reads exactly as the device wrote it.

    The result always carries a "redaction" block saying how many lines were
    changed. Redaction is pattern-based across five vendor syntaxes, so it
    REDUCES exposure rather than guaranteeing none remains — in particular it
    cannot see multi-line PKI key blocks.

    Prefer the CLI's '-o <path>' flag over include_secrets when a human needs
    the real config: it writes the raw text to a file instead of into this
    transcript.

    Args:
        include_secrets: True to return the verbatim config, credentials and
            all. Every secret in it then lives wherever this result is stored.
        target: Device name from config; omit to use the default device.
    """
    return ops.config_backup(_target(target), include_secrets=include_secrets)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def config_diff(
    config_text: str,
    replace: bool = False,
    include_secrets: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[READ] DRY-RUN: stage a candidate, return the diff, then discard it.

    Nothing is committed. This is the dry-run primitive for previewing a change.

    The diff is credential-redacted like config_backup, and for the same reason:
    a diff that ADDS 'snmp-server community X' contains X, and one that removes
    a line quotes the credential the device already had. The result carries a
    "redaction" block with the count.

    Args:
        config_text: The configuration snippet (merge) or full config (replace).
        replace: True to diff as a full-config replacement; False (default) to merge.
        include_secrets: True to return the verbatim diff — use when verifying
            that the literal key you are pushing is the one that will land.
        target: Device name from config.
    """
    return ops.config_diff(
        _target(target), config_text, replace=replace, include_secrets=include_secrets
    )


@mcp.tool()
@governed_tool(risk_level="medium", undo=_restore_undo)
@tool_errors("dict")
def config_merge(
    config_text: str,
    revert_in: int = DEFAULT_REVERT_IN,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Merge a config snippet and commit under a device-side revert timer.

    The device REVERTS the change by itself after ``revert_in`` seconds unless
    confirm_commit follows — so a change that severs your own management access
    heals without anyone having to reach the box. Verify reachability, THEN call
    confirm_commit. Check ``commit.safetyNet`` in the result: drivers that
    cannot arm a timer commit permanently and say so in ``commit.warning``.

    Returns ``diff`` and a ``backup`` digest (size + sha256). The full config is
    deliberately NOT returned — it carries credential hashes and PSKs — but the
    raw text is retained in undo.db for the recorded rollback. The ``diff`` is
    credential-redacted with no opt-out (see the ``redaction`` block); use
    config_diff(include_secrets=True) first if you must verify a literal key.

    dry_run=True stages the candidate, returns the diff, discards it, and runs
    the SAME refusal the real commit would — so a green preview is never
    followed by a refusal.

    Args:
        config_text: The configuration snippet to merge.
        revert_in: Device-side revert timer in seconds (default 300). 0 disables
            it, leaving the recorded undo as the only rollback path.
        dry_run: If True, preview the diff + safety assessment without committing.
        target: Device name from config.
    """
    if dry_run:
        return ops.config_preview(
            _target(target), config_text, replace=False, revert_in=revert_in
        )
    return ops.config_merge(_target(target), config_text, revert_in=revert_in)


@mcp.tool()
@governed_tool(risk_level="high", undo=_restore_undo)
@tool_errors("dict")
def config_replace(
    config_text: str,
    revert_in: int = DEFAULT_REVERT_IN,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Replace the full config and commit under a revert timer. HIGH RISK.

    Same commit-confirm contract as config_merge: the device reverts after
    ``revert_in`` seconds unless confirm_commit follows. Verify reachability
    first, then confirm. Check ``commit.safetyNet`` — when no timer could be
    armed the change is permanent on landing.

    Returns ``diff`` and a ``backup`` digest; the raw pre-change config is kept
    in undo.db (0600) for the recorded rollback, not echoed back here. The
    ``diff`` is credential-redacted with no opt-out (see the ``redaction``
    block); use config_diff(include_secrets=True) first if you must verify a
    literal key.

    dry_run=True previews the diff and runs the same refusal the real commit
    would, so the preview can never disagree with the commit.

    Args:
        config_text: The full replacement configuration.
        revert_in: Device-side revert timer in seconds (default 300). 0 disables
            it, leaving the recorded undo as the only rollback path.
        dry_run: If True, preview the diff + safety assessment without committing.
        target: Device name from config.
    """
    if dry_run:
        return ops.config_preview(
            _target(target), config_text, replace=True, revert_in=revert_in
        )
    return ops.config_replace(_target(target), config_text, revert_in=revert_in)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def confirm_commit(dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE] Confirm a pending commit-confirm change, cancelling its revert timer.

    The second half of the commit-confirm workflow. Run it only AFTER verifying
    the device is still reachable and healthy — doing nothing is the safe
    alternative, because the device then reverts on its own.

    dry_run=True reads whether a commit-confirm is actually pending (nothing is
    confirmed; the revert timer keeps running).

    Args:
        dry_run: If True, report whether a pending commit exists without confirming.
        target: Device name from config.
    """
    tgt = _target(target)
    if dry_run:
        return ops.preview_confirm_commit(tgt)
    return ops.confirm_commit(tgt)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def config_rollback(dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE] Revert the last committed change via NAPALM rollback(). No undo.

    Device support varies (rollback depth is platform-dependent).

    dry_run=True cannot predict the resulting config without the device, so it
    opens a session (verifying reachability) and reports a digest of the current
    running config — the state rollback would replace — without rolling back.

    Args:
        dry_run: If True, verify reachability and state what rollback would attempt.
        target: Device name from config.
    """
    tgt = _target(target)
    if dry_run:
        return ops.preview_rollback(tgt)
    return ops.config_rollback(tgt)
