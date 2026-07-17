"""Coverage for mcp_server._shared helpers (error sanitisation, tool_errors
result shapes, lazy manager/target/netbox resolution) and the ``undo`` CLI
sub-commands (list + confirmed apply) — all mocked.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import mcp_server._shared as shared
from network_aiops.config import AppConfig, TargetConfig
from network_aiops.connection import ConnectionManager, NetworkApiError

runner = CliRunner()
TARGET = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


# ── _safe_error / tool_errors shapes ────────────────────────────────────────


@pytest.mark.unit
def test_safe_error_passes_through_known_types():
    msg = shared._safe_error(NetworkApiError("device down"), "device_facts")
    assert "device down" in msg


@pytest.mark.unit
def test_safe_error_masks_unknown_types():
    """A non-allowlisted exception must NOT leak its message to the agent."""
    msg = shared._safe_error(RuntimeError("secret internal detail"), "device_facts")
    assert "secret internal detail" not in msg
    assert msg == "RuntimeError: operation failed."


@pytest.mark.unit
def test_tool_errors_list_shape():
    @shared.tool_errors("list")
    def boom():
        raise ValueError("nope")

    out = boom()
    assert isinstance(out, list)
    assert out[0]["error"].startswith("nope") or "nope" in out[0]["error"]
    assert "hint" in out[0]


@pytest.mark.unit
def test_tool_errors_str_shape():
    @shared.tool_errors("str")
    def boom():
        raise ValueError("nope")

    out = boom()
    assert isinstance(out, str)
    assert out.startswith("Error:")


# ── lazy manager / target / netbox resolution ───────────────────────────────


@pytest.mark.unit
def test_manager_lazy_builds_from_config(monkeypatch):
    monkeypatch.setattr(shared, "_conn_mgr", None)
    monkeypatch.delenv("NETWORK_AIOPS_CONFIG", raising=False)
    monkeypatch.setattr(shared, "load_config", lambda path: AppConfig(targets=(TARGET,)))
    mgr = shared._manager()
    assert isinstance(mgr, ConnectionManager)
    assert shared._target().name == "core-sw1"       # resolves via manager
    assert shared._target("core-sw1").name == "core-sw1"


@pytest.mark.unit
def test_manager_honours_config_path_env(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(shared, "_conn_mgr", None)
    monkeypatch.setenv("NETWORK_AIOPS_CONFIG", str(tmp_path / "cfg.yaml"))

    def _load(path):
        seen["path"] = path
        return AppConfig(targets=(TARGET,))

    monkeypatch.setattr(shared, "load_config", _load)
    shared._manager()
    assert str(seen["path"]).endswith("cfg.yaml")


@pytest.mark.unit
def test_netbox_helper_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(shared, "_conn_mgr", ConnectionManager(AppConfig(targets=(TARGET,))))
    with pytest.raises(NetworkApiError, match="not configured"):
        shared._netbox()


# ── undo CLI: list + confirmed apply (dispatches a synthetic inverse) ────────


@pytest.mark.unit
def test_undo_list_cli_prints_json(gov_home):
    from network_aiops.cli import app

    result = runner.invoke(app, ["undo", "list"])
    assert result.exit_code == 0, result.output
    assert "count" in result.output


@pytest.mark.unit
def test_undo_apply_cli_confirmed_dispatches_inverse(gov_home, monkeypatch):
    """`undo apply <id>` past the double-confirm dispatches the recorded inverse
    through its governed tool and marks the token applied."""
    import network_aiops.governance.undo as undo_mod
    from mcp_server._shared import mcp
    from network_aiops.cli import app
    from network_aiops.governance import governed_tool

    calls: list[str] = []

    @governed_tool(risk_level="low")
    def _cli_undo_probe(value: str = "", target=None) -> dict:
        calls.append(value)
        return {"ok": True}

    mcp.add_tool(_cli_undo_probe, name="_cli_undo_probe")
    monkeypatch.setenv("NETWORK_AUDIT_APPROVED_BY", "pytest")
    try:
        uid = undo_mod.get_undo_store().record(
            skill="probe", tool="orig",
            undo_descriptor={"tool": "_cli_undo_probe", "params": {"value": "restored"}},
        )
        result = runner.invoke(app, ["undo", "apply", uid], input="y\ny\n")
        assert result.exit_code == 0, result.output
        assert calls == ["restored"]
        assert undo_mod.get_undo_store().get(uid)["status"] == "applied"
    finally:
        mcp._tool_manager._tools.pop("_cli_undo_probe", None)
