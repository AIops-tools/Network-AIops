"""CLI confirmed-write path — past dry-run, through governance, onto disk.

The CLI write commands delegate real execution to the ``@governed_tool``
functions in ``mcp_server.tools``. These tests drive a write command PAST the
dry-run branch and the double-confirm prompts and assert the call really went
through the governed path (audit row on disk) — the regression test for the
"CLI writes were unaudited" line-wide fix.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import network_aiops.governance.audit as audit_mod
import network_aiops.governance.policy as policy_mod
import network_aiops.governance.undo as undo_mod
from network_aiops.config import TargetConfig


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NETWORK_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def fake_device(monkeypatch):
    """Route both the CLI's target resolution and the NAPALM driver to fakes."""
    import network_aiops.cli.config as cli_config
    import network_aiops.connection as conn_mod
    from mcp_server.tools import config_ops as gov

    target = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    driver_cls = MagicMock(name="driver_cls")
    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: driver_cls)
    monkeypatch.setattr(cli_config, "_resolve", lambda name=None: target)
    monkeypatch.setattr(gov, "_target", lambda name=None: target)
    return driver_cls


@pytest.mark.unit
def test_cli_config_rollback_dry_run_short_circuits_before_any_governed_call(
    gov_home, fake_device
):
    """config_rollback has no dry_run parameter, so there is no governed preview
    to route through — the CLI flag short-circuits client-side. Unlike merge /
    replace this makes no call at all, so there is nothing to audit."""
    from network_aiops.cli import app

    result = CliRunner().invoke(app, ["config", "rollback", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    fake_device.assert_not_called()  # no driver session was even opened
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_config_rollback_confirmed_goes_through_governance(gov_home, fake_device):
    """Confirmed CLI write must execute via the governed twin: the device call
    runs AND an audit row lands in audit.db (this is what the reroute fix bought)."""
    from network_aiops.cli import app

    result = CliRunner().invoke(app, ["config", "rollback"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    fake_device.return_value.rollback.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["config_rollback"]


@pytest.mark.unit
def test_cli_config_rollback_aborts_without_double_confirm(gov_home, fake_device):
    from network_aiops.cli import app

    result = CliRunner().invoke(app, ["config", "rollback"], input="y\nn\n")
    assert result.exit_code != 0
    fake_device.assert_not_called()
    assert not (gov_home / "audit.db").exists()


# ── commit-confirm reaches the CLI too ──────────────────────────────────────


@pytest.mark.unit
def test_cli_config_merge_arms_a_revert_timer(gov_home, fake_device, tmp_path):
    """The CLI must reach the same guarded path as MCP — not a bare commit."""
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.get_config.return_value = {"running": "hostname old\n"}
    dev.compare_config.return_value = "+ ntp server 10.0.0.99"
    cfg = tmp_path / "change.cfg"
    cfg.write_text("ntp server 10.0.0.99\n")

    result = CliRunner().invoke(app, ["config", "merge", str(cfg)], input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert dev.commit_config.call_args.kwargs["revert_in"] == 300
    assert _audit_tools(gov_home / "audit.db") == ["config_merge"]


@pytest.mark.unit
def test_cli_config_merge_honours_revert_in_flag(gov_home, fake_device, tmp_path):
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.get_config.return_value = {"running": "hostname old\n"}
    dev.compare_config.return_value = "+ x"
    cfg = tmp_path / "change.cfg"
    cfg.write_text("ntp server 10.0.0.99\n")

    result = CliRunner().invoke(
        app, ["config", "merge", str(cfg), "--revert-in", "60"], input="y\ny\n"
    )

    assert result.exit_code == 0, result.output
    assert dev.commit_config.call_args.kwargs["revert_in"] == 60


@pytest.mark.unit
def test_cli_config_confirm_goes_through_governance(gov_home, fake_device):
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.has_pending_commit.return_value = True

    result = CliRunner().invoke(app, ["config", "confirm"])

    assert result.exit_code == 0, result.output
    dev.confirm_commit.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["confirm_commit"]


@pytest.mark.unit
def test_cli_config_confirm_dry_run_opens_no_session(gov_home, fake_device):
    from network_aiops.cli import app

    result = CliRunner().invoke(app, ["config", "confirm", "--dry-run"])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    fake_device.assert_not_called()


@pytest.mark.unit
def test_cli_merge_dry_run_refuses_when_the_real_call_would(gov_home, fake_device, tmp_path):
    """The CLI preview must not disagree with the CLI commit."""
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.get_config.return_value = {"running": ""}  # no usable backup
    cfg = tmp_path / "change.cfg"
    cfg.write_text("ntp server 10.0.0.99\n")

    result = CliRunner().invoke(
        app, ["config", "merge", str(cfg), "--dry-run", "--revert-in", "0"]
    )

    assert result.exit_code != 0
    assert "irreversible" in result.output
    assert "DRY-RUN" not in result.output, (
        "a refused preview must not be introduced by a green 'no changes will be "
        "committed' banner it then contradicts — a weak model reads the banner as "
        "the answer and the refusal as transient"
    )
    dev.commit_config.assert_not_called()
    assert _audit_tools(gov_home / "audit.db") == ["config_merge"], (
        "the refused preview is still an audited governed call"
    )


@pytest.mark.unit
def test_cli_merge_dry_run_reads_and_audits_but_never_commits(gov_home, fake_device, tmp_path):
    """The invariant: a dry_run MAY read; it must never write.

    It reads (that is the only way it can answer "would this be refused?") and it
    lands an audit row like every other governed call — the MCP dry-run always
    did; the CLI silently skipping the audit was the outlier. What it must never
    do is issue the mutating call.
    """
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.get_config.return_value = {"running": "hostname old\n"}
    dev.compare_config.return_value = "+ ntp server 10.0.0.99"
    cfg = tmp_path / "change.cfg"
    cfg.write_text("ntp server 10.0.0.99\n")

    result = CliRunner().invoke(app, ["config", "merge", str(cfg), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "ntp server 10.0.0.99" in result.output
    assert "revert timer" in result.output
    assert "DRY-RUN" in result.output, "the human-readable banner must survive"
    dev.commit_config.assert_not_called(), "the one thing a dry-run may never do"
    assert _audit_tools(gov_home / "audit.db") == ["config_merge"]


@pytest.mark.unit
def test_cli_merge_dry_run_banner_reports_the_governed_answer_not_the_flag(
    gov_home, fake_device, tmp_path
):
    """Banner params come from the preview result, so they describe what the
    commit WOULD do — not what the flags asked for. A driver that cannot arm a
    revert timer must say 'undo-only' here even though --revert-in was 300."""
    from network_aiops.cli import app

    dev = fake_device.return_value
    dev.get_config.return_value = {"running": "hostname old\n"}
    dev.compare_config.return_value = "+ ntp server 10.0.0.99"

    # A driver whose commit_config takes no revert_in: no timer is possible.
    def _commit(message=""):
        raise AssertionError("a preview must never commit")

    dev.commit_config = _commit
    cfg = tmp_path / "change.cfg"
    cfg.write_text("ntp server 10.0.0.99\n")

    result = CliRunner().invoke(app, ["config", "merge", str(cfg), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "safetyNet = undo-only" in result.output
    assert "mode = merge" in result.output


# ── refusals must teach, not traceback ────────────────────────────────────────
#
# ``PolicyDenied``/``BudgetExceeded`` are raised by ``@governed_tool`` OUTSIDE the
# tool body, so ``tool_errors`` never flattens them into ``{"error": ...}`` and
# ``dry_run_preview``'s dict check cannot see them. Before they were listed in
# ``_cli_error_types`` a refused preview reached the operator as a raw traceback:
# the teaching text was in there, buried under a stack dump. A weak model reads
# that as a crash and retries — the very loop the preview reroute exists to stop.


def test_cli_error_types_covers_governance_refusals() -> None:
    """A governance refusal must be translated, not dumped as a traceback."""
    from network_aiops.cli._common import _cli_error_types
    from network_aiops.governance import BudgetExceeded, PolicyDenied

    types = _cli_error_types()
    assert PolicyDenied in types
    assert BudgetExceeded in types
