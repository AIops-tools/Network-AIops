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
def test_cli_config_rollback_dry_run_makes_no_call_and_no_audit(gov_home, fake_device):
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
