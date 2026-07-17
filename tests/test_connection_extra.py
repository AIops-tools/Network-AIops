"""Connection + config plumbing not covered elsewhere: NetBox client bootstrap
(unconfigured / missing-token / success), the ConnectionManager facade, extra
error-translation branches, and AppConfig target lookup. All mocked — no live
device or NetBox.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import network_aiops.connection as conn_mod
from network_aiops.config import AppConfig, NetBoxConfig, TargetConfig
from network_aiops.connection import (
    ConnectionManager,
    NetworkApiError,
    _translate,
    netbox_api,
)

TARGET = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


# ── netbox_api bootstrap ────────────────────────────────────────────────────


@pytest.mark.unit
def test_netbox_api_missing_token_teaches(monkeypatch):
    nb = NetBoxConfig(url="http://nb.local")
    monkeypatch.setattr(NetBoxConfig, "token", lambda self: "")
    with pytest.raises(NetworkApiError, match="token missing"):
        netbox_api(nb)


@pytest.mark.unit
def test_netbox_api_success_builds_client(monkeypatch):
    """With a token + pynetbox importable, netbox_api returns pynetbox.api(...)."""
    import sys
    import types

    nb = NetBoxConfig(url="http://nb.local")
    monkeypatch.setattr(NetBoxConfig, "token", lambda self: "tok")

    fake_pynetbox = types.ModuleType("pynetbox")
    sentinel = object()
    fake_pynetbox.api = MagicMock(return_value=sentinel)
    monkeypatch.setitem(sys.modules, "pynetbox", fake_pynetbox)

    assert netbox_api(nb) is sentinel
    fake_pynetbox.api.assert_called_once_with("http://nb.local", token="tok")


@pytest.mark.unit
def test_netbox_api_client_init_failure_teaches(monkeypatch):
    import sys
    import types

    nb = NetBoxConfig(url="http://nb.local")
    monkeypatch.setattr(NetBoxConfig, "token", lambda self: "tok")
    fake_pynetbox = types.ModuleType("pynetbox")
    fake_pynetbox.api = MagicMock(side_effect=RuntimeError("bad url"))
    monkeypatch.setitem(sys.modules, "pynetbox", fake_pynetbox)

    with pytest.raises(NetworkApiError, match="Could not initialise the NetBox client"):
        netbox_api(nb)


# ── ConnectionManager facade ────────────────────────────────────────────────


@pytest.mark.unit
def test_connection_manager_resolves_default_and_named_target():
    t2 = TargetConfig(name="edge-1", driver="ios", host="10.0.0.9", username="admin")
    mgr = ConnectionManager(AppConfig(targets=(TARGET, t2)))
    assert mgr.target().name == "core-sw1"        # default = first
    assert mgr.target("edge-1").name == "edge-1"  # named lookup
    assert mgr.list_targets() == ["core-sw1", "edge-1"]
    assert mgr.config.targets[0].name == "core-sw1"


@pytest.mark.unit
def test_connection_manager_session_returns_context_manager(fake_driver_cls):
    mgr = ConnectionManager(AppConfig(targets=(TARGET,)))
    with mgr.session() as dev:
        assert dev.opened is True
    assert dev.closed is True


@pytest.mark.unit
def test_connection_manager_netbox_raises_when_unconfigured():
    mgr = ConnectionManager(AppConfig(targets=(TARGET,), netbox=None))
    with pytest.raises(NetworkApiError, match="not configured"):
        mgr.netbox()


@pytest.mark.unit
def test_connection_manager_from_config_uses_loader(monkeypatch):
    cfg = AppConfig(targets=(TARGET,))
    monkeypatch.setattr(conn_mod, "load_config", lambda: cfg)
    mgr = ConnectionManager.from_config()
    assert mgr.config is cfg


# ── error translation branches ──────────────────────────────────────────────


@pytest.mark.unit
def test_translate_command_error_mentions_privilege():
    # NAPALM's real class is CommandErrorException; _translate matches on
    # type(exc).__name__, so build a type with that exact name.
    cmd_exc = type("CommandErrorException", (Exception,), {})
    err = _translate(cmd_exc("nope"), TARGET)
    assert "rejected a command" in str(err)


@pytest.mark.unit
def test_translate_generic_exception_is_wrapped():
    err = _translate(RuntimeError("weird failure"), TARGET)
    assert isinstance(err, NetworkApiError)
    assert "failed" in str(err).lower()


@pytest.mark.unit
def test_device_session_translates_in_session_error(monkeypatch, eos_target):
    """An exception raised INSIDE the with-block is translated + the session
    is still closed."""
    from tests.conftest import FakeDriver

    class Boom(FakeDriver):
        def get_facts(self):
            raise RuntimeError("mid-session blowup")

    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: Boom)
    with pytest.raises(NetworkApiError, match="failed"):
        with conn_mod.device_session(eos_target) as dev:
            dev.get_facts()
    assert dev.closed is True


@pytest.mark.unit
def test_device_session_open_failure_is_translated(monkeypatch, eos_target):
    from tests.conftest import FakeDriver

    class NoOpen(FakeDriver):
        def open(self):
            raise type("ConnectionException", (Exception,), {})("no route")

    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: NoOpen)
    with pytest.raises(NetworkApiError, match="connect/authenticate"):
        with conn_mod.device_session(eos_target):
            pass


# ── AppConfig lookup edges ──────────────────────────────────────────────────


@pytest.mark.unit
def test_appconfig_get_target_unknown_lists_available():
    cfg = AppConfig(targets=(TARGET,))
    with pytest.raises(KeyError, match="core-sw1"):
        cfg.get_target("missing")


@pytest.mark.unit
def test_appconfig_default_target_empty_raises():
    with pytest.raises(ValueError, match="No devices configured"):
        _ = AppConfig().default_target
