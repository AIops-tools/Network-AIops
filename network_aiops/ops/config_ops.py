"""Configuration operations: backup, diff (dry-run), merge, replace, rollback, confirm.

NAPALM config workflow:
  - ``get_config(retrieve="running")`` reads the running config (backup).
  - ``load_merge_candidate`` / ``load_replace_candidate`` stage a candidate.
  - ``compare_config()`` returns the diff WITHOUT committing.
  - ``commit_config()`` applies the staged candidate.
  - ``commit_config(revert_in=N)`` applies it with a device-side revert timer:
    the device rolls the change back on its own after ``N`` seconds unless
    ``confirm_commit()`` arrives first.
  - ``discard_config()`` throws the candidate away (used by the dry-run diff).
  - ``rollback()`` reverts the last commit (device support varies).

**Why commit-confirm is the primary safety net here.** The recorded undo for a
config write is a ``config_replace`` back to the captured backup, and that
inverse needs a BRAND-NEW session to the same device. A change that shuts the
management interface, tightens the VTY ACL, or breaks AAA severs exactly that
path: the write lands, the session dies, and the undo token sits in undo.db
permanently unreachable. A revert timer is the only guard that survives the
device becoming unreachable, because the *device* enforces it — the lockout
self-heals without anyone being able to reach the box. So the default workflow
is:

    config_merge / config_replace (arms a timer)
      → verify you can still reach the device
      → confirm_commit  (or do nothing and let the device revert)

Drivers that cannot arm a timer (``NotImplementedError`` from NAPALM, or an
older driver whose ``commit_config`` has no ``revert_in`` parameter) fall back
to a plain commit — but say so loudly in the result, because for those devices
the safety net is simply absent and the operator has to know that.

**Backup handling.** Write ops capture the pre-change running config first. The
RAW text is handed to the harness via ``capture_prior_state`` so the recorded
undo replays a byte-exact config; it is deliberately NOT returned to the caller.
A running config carries credential hashes, SNMP communities, PSKs and RADIUS
keys, and a tool result goes straight into an agent transcript — so the caller
gets a digest (size + SHA-256 + whether an undo copy was retained) instead. Only
the diff, which is what the operator actually asked about, is echoed back.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
from typing import Any

from network_aiops.governance import capture_prior_state
from network_aiops.ops._shared import s

_log = logging.getLogger("network-aiops.config")

# Bound for caller-facing config/diff text (display hygiene, not undo).
_MAX_CONFIG = 200_000

# Completeness ceiling for the RAW copy retained for undo. Deliberately far
# above the display bound: reusing 200k here would strip the rollback from
# exactly the largest chassis, which are the devices where a lockout hurts
# most. Still bounded — an unbounded blob into SQLite is its own hazard.
_MAX_UNDO_CONFIG = 4_000_000

# Default device-side revert timer for a governed commit, in seconds. Long
# enough to log in and check reachability, short enough that an unattended
# lockout heals within one coffee break.
DEFAULT_REVERT_IN = 300

_BACKUP_NOTE = (
    "Full pre-change config withheld from this result: it contains credential "
    "hashes, SNMP communities, PSKs and RADIUS keys. The complete raw text is "
    "retained in undo.db (0600) for the recorded rollback. Use config_backup "
    "if you deliberately want the text."
)


class UnreversibleCommit(ValueError):  # noqa: N818 — teaching error, reads as a statement
    """Refused: the commit would have neither a revert timer nor a usable undo."""


def _running_config(dev: Any) -> str:
    """Read the running config as a string."""
    cfg = dev.get_config(retrieve="running")
    return cfg.get("running", "") if isinstance(cfg, dict) else str(cfg)


def _accepts_revert_in(dev: Any) -> bool:
    """Whether this driver's ``commit_config`` takes a ``revert_in`` parameter.

    Fails OPEN: when the signature cannot be read we assume it does and let the
    driver's own ``NotImplementedError`` be the authority. Guessing "no" here
    would silently drop the safety net on a driver that actually supports it.
    """
    try:
        params = inspect.signature(dev.commit_config).parameters
    except (TypeError, ValueError):
        return True
    if "revert_in" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _backup_digest(raw: str, retained: bool) -> dict:
    """Caller-safe summary of the captured pre-change config (never the text)."""
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(),
        "retainedForUndo": retained,
        "note": _BACKUP_NOTE,
    }


def _refuse_unreversible(action: str, raw: str) -> None:
    """Refuse a commit that would have no revert timer AND no usable undo.

    Fires only when BOTH nets are provably gone. Raised by the caller *after*
    the device session has closed — ``device_session`` translates every
    in-session exception into a ``NetworkApiError``, which would bury the
    refusal behind a generic "device operation failed". Nothing was committed
    either way, so refusing costs the operator nothing but a retry.
    """
    if len(raw) > _MAX_UNDO_CONFIG:
        why = (
            f"the pre-change config is {len(raw)} chars, over the "
            f"{_MAX_UNDO_CONFIG}-char ceiling for a retained undo copy"
        )
    else:
        why = "the device returned an empty pre-change config, so there is nothing to restore"
    raise UnreversibleCommit(
        f"Refusing to {action}: this device cannot arm a commit-confirm revert timer "
        f"(or one was not requested), and {why}. The commit would therefore be "
        f"irreversible — if it severs management access there is no timer to heal it "
        f"and no rollback to replay. Save a config off-box first "
        f"('network-aiops config backup -o backup.cfg'), then retry."
    )


def _plain_commit_descriptor(reason: str) -> dict:
    """Descriptor for a commit that landed with NO device-side revert timer."""
    return {
        "mode": "commit",
        "revertInSeconds": None,
        "confirmed": True,
        "safetyNet": "undo-only",
        "warning": (
            f"NO COMMIT-CONFIRM SAFETY NET: a revert timer {reason}, so the change is "
            f"permanent the moment it lands. Rollback depends on the recorded undo, "
            f"which needs a NEW session to this device — a change that severs "
            f"management access cannot be undone remotely. Verify reachability NOW "
            f"and be ready with out-of-band access."
        ),
        "next": "Verify reachability immediately; undo_apply needs a working session.",
    }


def _commit(dev: Any, *, revert_in: int, raw: str) -> dict | None:
    """Commit the staged candidate, arming a device-side revert timer if possible.

    Returns a descriptor of HOW it committed, so the caller can never be left
    assuming a safety net that is not there — or ``None`` when it committed
    NOTHING because neither a timer nor a usable undo would exist (the caller
    turns that into an :class:`UnreversibleCommit` once the session is closed).
    """
    retained = _is_retainable(raw)
    timer_refused = False
    if revert_in > 0 and _accepts_revert_in(dev):
        try:
            dev.commit_config(revert_in=revert_in)
        except NotImplementedError:
            # NAPALM validates revert_in before applying, so nothing landed.
            timer_refused = True
        else:
            return {
                "mode": "commit-confirm",
                "revertInSeconds": revert_in,
                "confirmed": False,
                "safetyNet": "commit-confirm",
                "warning": None,
                "next": (
                    f"The device will REVERT this change in {revert_in}s unless you "
                    f"confirm it. Verify you can still reach the device, then run "
                    f"confirm_commit ('network-aiops config confirm')."
                ),
            }
    if not retained:
        return None
    dev.commit_config()
    if timer_refused:
        return _plain_commit_descriptor("is unsupported by this NAPALM driver")
    return _plain_commit_descriptor(
        "was not requested (revert_in<=0)" if revert_in <= 0 else "is unavailable"
    )


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


def _is_retainable(raw: str) -> bool:
    """Whether ``raw`` is a complete-enough pre-change config to base an undo on."""
    return bool(raw.strip()) and len(raw) <= _MAX_UNDO_CONFIG


def config_preview(target: Any, config_text: str, *, replace: bool, revert_in: int) -> dict:
    """[READ / DRY-RUN] The diff the write would produce + the safety it would have.

    Runs the same both-nets-gone refusal as the real write, so a preview can
    never come back green for a call that is about to be refused — a weak model
    reads that refusal as transient and retries.

    The one asymmetry is deliberate and safe in the right direction: a dry-run
    can only *predict* commit-confirm support from the driver's signature,
    whereas the real write also learns from a ``NotImplementedError`` raised at
    commit time. So the dry-run's refusal condition is a strict SUBSET of the
    write's — it never refuses something the write would allow. Nothing is
    committed here; the candidate is always discarded.
    """
    from network_aiops.connection import device_session

    action = "replace the config of" if replace else "merge config into"
    with device_session(target) as dev:
        raw = _running_config(dev)
        retained = _is_retainable(raw)
        timer_likely = revert_in > 0 and _accepts_revert_in(dev)
        if replace:
            dev.load_replace_candidate(config=config_text)
        else:
            dev.load_merge_candidate(config=config_text)
        try:
            diff = dev.compare_config()
        finally:
            dev.discard_config()
    if not timer_likely and not retained:
        _refuse_unreversible(action, raw)
    return {
        "name": s(target.name, 128),
        "dryRun": True,
        "mode": "replace" if replace else "merge",
        "diff": sanitize_config(diff),
        "committed": False,
        "backup": _backup_digest(raw, retained),
        "commit": {
            "wouldArmTimer": timer_likely,
            "revertInSeconds": revert_in if timer_likely else None,
            "safetyNet": "commit-confirm" if timer_likely else "undo-only",
            "warning": None
            if timer_likely
            else (
                "This driver's commit_config takes no revert_in (or revert_in<=0 was "
                "passed), so the real commit would be PERMANENT on landing. Rollback "
                "would depend on the recorded undo, which needs a working session."
            ),
        },
        "note": "Dry-run only — no changes were committed.",
    }


def _discard_quietly(dev: Any) -> None:
    """Drop a staged candidate on the refusal path.

    Best-effort: the refusal is the message the operator needs, and a driver
    that cannot discard must not replace it with a confusing secondary error.
    The candidate is uncommitted either way.
    """
    try:
        dev.discard_config()
    except Exception:  # noqa: BLE001 — must not mask the refusal
        _log.warning("could not discard the staged candidate after refusing", exc_info=True)


def _write_config(target: Any, config_text: str, *, replace: bool, revert_in: int) -> dict:
    """Shared body of merge/replace: capture, stage, diff, commit-with-timer."""
    from network_aiops.connection import device_session

    action = "replace the config of" if replace else "merge config into"
    with device_session(target) as dev:
        raw = _running_config(dev)
        retained = _is_retainable(raw)
        if retained:
            # Hand the harness the RAW text before the mutating call, so the
            # inverse survives even a lost response — and so the config body
            # never has to travel back through the caller's result.
            capture_prior_state({"running": raw})
        if replace:
            dev.load_replace_candidate(config=config_text)
        else:
            dev.load_merge_candidate(config=config_text)
        diff = dev.compare_config()
        commit = _commit(dev, revert_in=revert_in, raw=raw)
        if commit is None:
            # Nothing was committed. Drop the staged candidate so the device is
            # left exactly as we found it, then refuse outside the session.
            _discard_quietly(dev)
    if commit is None:
        _refuse_unreversible(action, raw)
    return {
        "name": s(target.name, 128),
        "action": "replaced" if replace else "merged",
        "committed": True,
        "diff": sanitize_config(diff),
        "backup": _backup_digest(raw, retained),
        "commit": commit,
    }


def config_merge(target: Any, config_text: str, revert_in: int = DEFAULT_REVERT_IN) -> dict:
    """[WRITE] Merge a config snippet and commit under a device-side revert timer.

    Captures the pre-change running config for undo (raw, via the harness) and
    returns ``diff`` plus a ``backup`` digest — never the config body itself.
    ``commit`` reports whether a revert timer was actually armed; when it was,
    the change REVERTS on its own unless ``confirm_commit`` follows.
    """
    return _write_config(target, config_text, replace=False, revert_in=revert_in)


def config_replace(target: Any, config_text: str, revert_in: int = DEFAULT_REVERT_IN) -> dict:
    """[WRITE / HIGH] Replace the full config and commit under a revert timer.

    Same contract as ``config_merge``, but the candidate is a full-config
    replacement. The recorded undo replaces the config back to the captured
    backup — which needs a working session, hence the timer.
    """
    return _write_config(target, config_text, replace=True, revert_in=revert_in)


def confirm_commit(target: Any) -> dict:
    """[WRITE] Confirm a pending commit-confirm change, cancelling its revert timer.

    The second half of the commit-confirm workflow: once you have verified the
    device is still reachable and behaving, this makes the change permanent.
    Doing nothing is the safe alternative — the device reverts on its own.
    """
    from network_aiops.connection import device_session

    with device_session(target) as dev:
        pending = _has_pending_commit(dev)
        if pending is False:
            return {
                "name": s(target.name, 128),
                "action": "confirm_commit",
                "hadPendingCommit": False,
                "confirmed": False,
                "note": (
                    "No pending commit-confirm on this device — nothing to confirm. "
                    "Either it was already confirmed, the revert timer already fired, "
                    "or the commit was made without a timer."
                ),
            }
        dev.confirm_commit()
    return {
        "name": s(target.name, 128),
        "action": "confirm_commit",
        "hadPendingCommit": pending,
        "confirmed": True,
        "note": "Revert timer cancelled — the pending change is now permanent.",
    }


def _has_pending_commit(dev: Any) -> bool | None:
    """Whether a commit-confirm is pending; ``None`` when the driver cannot say.

    Unknown must never read as "nothing pending" — that would talk an operator
    out of confirming a change that is about to revert under them.
    """
    try:
        return bool(dev.has_pending_commit())
    except (NotImplementedError, AttributeError):
        return None


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
