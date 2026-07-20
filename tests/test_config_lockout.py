"""Commit-confirm: the guard that survives the change locking us out.

The recorded undo for a config write is a ``config_replace`` back to the captured
backup, and that inverse opens a BRAND-NEW session to the same device. A commit
that shuts the management interface, tightens the VTY ACL or breaks AAA severs
exactly that path — the write lands, the session dies, and the undo token sits
in undo.db permanently unreachable. NAPALM's ``commit_config(revert_in=N)`` is
the only guard that survives that, because the *device* enforces it: the lockout
self-heals with nobody able to reach the box.

These tests pin the three things that make it real rather than decorative:
the timer is actually armed, the fallback for drivers that cannot arm one is
LOUD, and the config body (credential hashes, SNMP communities, PSKs) never
travels back to the caller while the undo still gets the byte-exact original.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from network_aiops.config import TargetConfig
from network_aiops.ops import config_ops
from network_aiops.ops.config_ops import DEFAULT_REVERT_IN, UnreversibleCommit

TARGET = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")

_RUNNING = "hostname core-sw1\nsnmp-server community s3cr3t ro\n"


class _Driver:
    """A NAPALM driver double whose commit-confirm support is configurable."""

    def __init__(self, *, supports_revert=True, running=_RUNNING):
        self.supports_revert = supports_revert
        self.running = running
        self.commits: list[int | None] = []
        self.pending = False
        self.confirmed = False

    def open(self):
        pass

    def close(self):
        pass

    def get_config(self, retrieve="running"):
        return {"running": self.running}

    def load_merge_candidate(self, config=None):
        pass

    def load_replace_candidate(self, config=None):
        pass

    def compare_config(self):
        return "+ ntp server 10.0.0.99"

    def discard_config(self):
        pass

    def commit_config(self, message="", revert_in=None):
        if revert_in is not None and not self.supports_revert:
            # NAPALM validates revert_in BEFORE applying anything, so nothing
            # is committed on this path.
            raise NotImplementedError("revert_in is not supported on this platform")
        self.commits.append(revert_in)
        self.pending = revert_in is not None

    def has_pending_commit(self):
        return self.pending

    def confirm_commit(self):
        self.confirmed = True
        self.pending = False


@pytest.fixture
def driver(monkeypatch):
    """Route ``device_session`` at a configurable driver double."""
    dev = _Driver()
    import network_aiops.connection as conn_mod

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: lambda **kw: dev)
    return dev


# ── the timer is really armed ───────────────────────────────────────────────


@pytest.mark.unit
def test_config_merge_commits_with_a_revert_timer_by_default(driver):
    """Default behaviour must be the safe one — no opt-in required."""
    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert driver.commits == [DEFAULT_REVERT_IN], "commit_config must carry revert_in"
    assert result["commit"]["mode"] == "commit-confirm"
    assert result["commit"]["revertInSeconds"] == DEFAULT_REVERT_IN
    assert result["commit"]["safetyNet"] == "commit-confirm"
    assert result["commit"]["confirmed"] is False
    assert result["commit"]["warning"] is None


@pytest.mark.unit
def test_config_replace_passes_an_explicit_revert_in(driver):
    config_ops.config_replace(TARGET, "hostname new\n", revert_in=120)
    assert driver.commits == [120]


@pytest.mark.unit
def test_revert_in_zero_commits_plainly_and_warns(driver):
    """Disabling the timer is allowed, but the caller must be told the net is off."""
    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99", revert_in=0)

    assert driver.commits == [None] or driver.commits == [], driver.commits
    assert result["commit"]["mode"] == "commit"
    assert result["commit"]["safetyNet"] == "undo-only"
    assert "NO COMMIT-CONFIRM SAFETY NET" in result["commit"]["warning"]


# ── graceful degradation, loudly ────────────────────────────────────────────


@pytest.mark.unit
def test_driver_without_revert_in_falls_back_and_says_so_loudly(driver):
    """NotImplementedError must degrade to today's behaviour — never fail the write."""
    driver.supports_revert = False

    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert driver.commits == [None], "must retry as a plain commit"
    assert result["committed"] is True
    assert result["commit"]["mode"] == "commit"
    assert result["commit"]["safetyNet"] == "undo-only"
    warning = result["commit"]["warning"]
    assert "NO COMMIT-CONFIRM SAFETY NET" in warning
    assert "out-of-band" in warning, "must tell the operator what to arrange instead"


@pytest.mark.unit
def test_signature_probe_fails_open_when_it_cannot_be_read():
    """Unknown driver signature must mean 'try the timer', never 'skip it'."""
    dev = MagicMock(name="driver")
    assert config_ops._accepts_revert_in(dev) is True


@pytest.mark.unit
def test_signature_probe_accepts_kwargs_only_drivers():
    class _Kwargs:
        def commit_config(self, **kwargs):
            pass

    assert config_ops._accepts_revert_in(_Kwargs()) is True


@pytest.mark.unit
def test_signature_probe_rejects_a_driver_without_the_parameter():
    class _Old:
        def commit_config(self, message=""):
            pass

    assert config_ops._accepts_revert_in(_Old()) is False


@pytest.mark.unit
def test_old_driver_signature_still_commits(monkeypatch):
    """A pre-3.0 driver whose commit_config has no revert_in must still work."""
    committed = []

    class _Old:
        def open(self):
            pass

        def close(self):
            pass

        def get_config(self, retrieve="running"):
            return {"running": _RUNNING}

        def load_merge_candidate(self, config=None):
            pass

        def compare_config(self):
            return "+ x"

        def commit_config(self, message=""):
            committed.append(True)

    import network_aiops.connection as conn_mod

    dev = _Old()
    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: lambda **kw: dev)

    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")
    assert committed == [True]
    assert result["commit"]["safetyNet"] == "undo-only"


# ── refusing the commit that would have no net at all ───────────────────────


@pytest.mark.unit
def test_refuses_when_there_is_neither_a_timer_nor_a_usable_backup(driver):
    """Both nets provably gone → refuse, before anything is committed."""
    driver.supports_revert = False
    driver.running = ""  # nothing to restore

    with pytest.raises(UnreversibleCommit, match="irreversible"):
        config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert driver.commits == [], "must refuse BEFORE committing"


@pytest.mark.unit
def test_refusal_names_the_way_out(driver):
    driver.supports_revert = False
    driver.running = ""
    with pytest.raises(UnreversibleCommit) as ei:
        config_ops.config_merge(TARGET, "ntp server 10.0.0.99")
    assert "config backup -o" in str(ei.value), "must offer a concrete way forward"


@pytest.mark.unit
def test_refuses_when_backup_is_over_the_undo_ceiling(driver, monkeypatch):
    driver.supports_revert = False
    monkeypatch.setattr(config_ops, "_MAX_UNDO_CONFIG", 10)
    with pytest.raises(UnreversibleCommit, match="ceiling"):
        config_ops.config_merge(TARGET, "hostname x\n")


@pytest.mark.unit
def test_an_armed_timer_alone_is_enough_to_proceed(driver):
    """Fail open: an unusable backup must NOT block a write that has a timer."""
    driver.running = ""  # no undo possible

    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert driver.commits == [DEFAULT_REVERT_IN]
    assert result["backup"]["retainedForUndo"] is False
    assert result["commit"]["safetyNet"] == "commit-confirm"


@pytest.mark.unit
def test_a_usable_backup_alone_is_enough_to_proceed(driver):
    """Fail open: no timer is fine as long as a real rollback was captured."""
    driver.supports_revert = False

    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert result["committed"] is True
    assert result["backup"]["retainedForUndo"] is True


# ── the config body must not reach the caller ───────────────────────────────


@pytest.mark.unit
def test_result_carries_a_digest_not_the_config_body(driver):
    """A running config holds credential hashes and SNMP communities; a tool
    result goes straight into the agent transcript."""
    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    assert "s3cr3t" not in str(result), "the community string must not be echoed back"
    backup = result["backup"]
    assert backup["bytes"] == len(_RUNNING)
    assert len(backup["sha256"]) == 64
    assert backup["retainedForUndo"] is True


@pytest.mark.unit
def test_raw_backup_is_handed_to_the_harness_not_truncated_or_sanitized(driver):
    """The undo copy must be byte-exact: sanitize() would strip a banner's control
    characters and the old display cap would replay a TRUNCATED config."""
    from network_aiops.governance.outcome import take_prior_state

    driver.running = "banner motd \x01hello\x01\n" + "x" * 250_000

    config_ops.config_merge(TARGET, "ntp server 10.0.0.99")

    prior = take_prior_state()
    assert prior is not None, "the raw config must be stashed for the undo"
    assert prior["running"] == driver.running, "byte-exact, not sanitized or truncated"


@pytest.mark.unit
def test_no_prior_state_is_stashed_when_the_backup_is_unusable(driver):
    from network_aiops.governance.outcome import take_prior_state

    driver.running = ""
    config_ops.config_merge(TARGET, "ntp server 10.0.0.99")
    assert take_prior_state() is None, "must not record an undo it cannot honour"


# ── confirm_commit ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_confirm_commit_confirms_a_pending_change(driver):
    config_ops.config_merge(TARGET, "ntp server 10.0.0.99")
    assert driver.pending is True

    result = config_ops.confirm_commit(TARGET)

    assert driver.confirmed is True
    assert result["confirmed"] is True
    assert result["hadPendingCommit"] is True


@pytest.mark.unit
def test_confirm_commit_reports_when_nothing_is_pending(driver):
    result = config_ops.confirm_commit(TARGET)
    assert result["confirmed"] is False
    assert result["hadPendingCommit"] is False
    assert driver.confirmed is False


@pytest.mark.unit
def test_unknown_pending_state_still_confirms(monkeypatch):
    """Fail open: a driver that cannot report pending state must not talk the
    operator out of confirming a change that is about to revert under them."""
    confirmed = []

    class _NoPendingApi:
        def open(self):
            pass

        def close(self):
            pass

        def confirm_commit(self):
            confirmed.append(True)

    import network_aiops.connection as conn_mod

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: lambda **kw: _NoPendingApi())

    result = config_ops.confirm_commit(TARGET)

    assert confirmed == [True], "unknown must not be read as 'nothing pending'"
    assert result["hadPendingCommit"] is None
    assert result["confirmed"] is True


# ── MCP + undo wiring ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_merge_threads_revert_in_through(driver, monkeypatch):
    from mcp_server.tools import config_ops as cfg_tools

    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: TARGET)
    cfg_tools.config_merge(config_text="ntp server 10.0.0.99", revert_in=45)
    assert driver.commits == [45]


@pytest.mark.unit
def test_recorded_inverse_carries_raw_config_and_disables_its_own_timer(
    driver, monkeypatch
):
    """The rollback must be permanent: nobody confirms an undo, so an inverse
    that armed its own timer would put the broken config straight back."""
    import network_aiops.governance.undo as undo_mod
    from mcp_server.tools import config_ops as cfg_tools

    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: TARGET)
    recorded: dict = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params, effect_verified=True):
            recorded["descriptor"] = undo_descriptor
            return "undo-1"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    result = cfg_tools.config_merge(config_text="ntp server 10.0.0.99")

    params = recorded["descriptor"]["params"]
    assert params["config_text"] == _RUNNING, "the inverse replays the byte-exact original"
    assert params["revert_in"] == 0, "a rollback must not sit under a revert timer"
    assert "s3cr3t" not in str(result), "still not echoed to the caller"


@pytest.mark.unit
def test_no_inverse_is_recorded_without_a_usable_backup(driver, monkeypatch):
    import network_aiops.governance.undo as undo_mod
    from mcp_server.tools import config_ops as cfg_tools

    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: TARGET)
    driver.running = ""
    recorded: list = []

    class _Store:
        def record(self, **kwargs):
            recorded.append(kwargs)
            return "undo-1"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    cfg_tools.config_merge(config_text="ntp server 10.0.0.99")
    assert recorded == [], "an undo that replays an empty config is worse than none"


# ── dry_run must not bypass the guard ───────────────────────────────────────


@pytest.mark.unit
def test_dry_run_refuses_what_the_write_would_refuse(driver):
    """A green preview followed by a refusal reads as transient to a weak model,
    which then retries. The preview has to give the same answer."""
    driver.running = ""  # no usable backup

    with pytest.raises(UnreversibleCommit, match="irreversible"):
        # revert_in=0 disables the timer: both nets provably gone.
        config_ops.config_preview(TARGET, "ntp server 10.0.0.99", replace=False, revert_in=0)

    assert driver.commits == [], "a preview never commits"


@pytest.mark.unit
def test_the_write_refuses_the_same_case_the_preview_did(driver):
    """The two must agree — that is the whole point."""
    driver.running = ""
    with pytest.raises(UnreversibleCommit):
        config_ops.config_merge(TARGET, "ntp server 10.0.0.99", revert_in=0)


@pytest.mark.unit
def test_dry_run_previews_normally_when_the_write_would_be_allowed(driver):
    """Fail open, identically to the write: a usable backup is enough."""
    out = config_ops.config_preview(
        TARGET, "ntp server 10.0.0.99", replace=False, revert_in=0
    )

    assert out["dryRun"] is True and out["committed"] is False
    assert out["diff"] == "+ ntp server 10.0.0.99"
    assert out["backup"]["retainedForUndo"] is True
    assert out["commit"]["wouldArmTimer"] is False
    assert "PERMANENT" in out["commit"]["warning"]


@pytest.mark.unit
def test_dry_run_refuses_for_an_old_signature_driver_with_no_backup(monkeypatch):
    """The preview's only timer signal is the signature — it must use it."""

    class _Old:
        def open(self):
            pass

        def close(self):
            pass

        def get_config(self, retrieve="running"):
            return {"running": ""}

        def load_merge_candidate(self, config=None):
            pass

        def compare_config(self):
            return "+ x"

        def discard_config(self):
            pass

        def commit_config(self, message=""):
            raise AssertionError("a preview must never commit")

    import network_aiops.connection as conn_mod

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: lambda **kw: _Old())

    with pytest.raises(UnreversibleCommit):
        config_ops.config_preview(TARGET, "x", replace=False, revert_in=300)


@pytest.mark.unit
def test_dry_run_predicts_the_timer_when_the_driver_supports_it(driver):
    out = config_ops.config_preview(TARGET, "x", replace=False, revert_in=120)
    assert out["commit"]["wouldArmTimer"] is True
    assert out["commit"]["revertInSeconds"] == 120
    assert out["commit"]["safetyNet"] == "commit-confirm"
    assert out["commit"]["warning"] is None


@pytest.mark.unit
def test_dry_run_with_a_timer_does_not_refuse_an_unusable_backup(driver):
    """The timer alone is a net — the preview must agree with the write."""
    driver.running = ""
    out = config_ops.config_preview(TARGET, "x", replace=False, revert_in=300)
    assert out["backup"]["retainedForUndo"] is False
    assert out["commit"]["wouldArmTimer"] is True


@pytest.mark.unit
def test_dry_run_never_refuses_what_the_write_allows(driver):
    """The refusal condition must be a strict SUBSET of the write's.

    The preview can only predict timer support from the signature; the write
    also learns from a NotImplementedError at commit time. That asymmetry is
    only safe in one direction.
    """
    # Signature says yes, driver raises at commit time: preview allows, write
    # falls back to undo-only (and refuses only if the backup is unusable too).
    driver.supports_revert = False
    preview = config_ops.config_preview(TARGET, "x", replace=False, revert_in=300)
    assert preview["dryRun"] is True, "preview must not refuse here"
    result = config_ops.config_merge(TARGET, "x", revert_in=300)
    assert result["committed"] is True, "and the write goes through too"


@pytest.mark.unit
def test_dry_run_discards_the_candidate(driver):
    discarded = []
    driver.discard_config = lambda: discarded.append(True)
    config_ops.config_preview(TARGET, "x", replace=True, revert_in=300)
    assert discarded == [True]


@pytest.mark.unit
def test_dry_run_does_not_leak_the_config_body(driver):
    out = config_ops.config_preview(TARGET, "x", replace=False, revert_in=300)
    assert "s3cr3t" not in str(out)
    assert out["backup"]["sha256"]


@pytest.mark.unit
def test_mcp_dry_run_refuses_and_makes_no_commit(driver, monkeypatch):
    from mcp_server.tools import config_ops as cfg_tools

    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: TARGET)
    driver.running = ""

    out = cfg_tools.config_merge(config_text="x", dry_run=True, revert_in=0)

    assert "error" in out, "the governed wrapper surfaces the refusal"
    assert "irreversible" in out["error"]
    assert driver.commits == []


@pytest.mark.unit
def test_mcp_dry_run_previews_an_allowed_write(driver, monkeypatch):
    from mcp_server.tools import config_ops as cfg_tools

    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: TARGET)

    out = cfg_tools.config_replace(config_text="hostname new\n", dry_run=True)

    assert out["dryRun"] is True and out["committed"] is False
    assert out["mode"] == "replace"
    assert driver.commits == []
