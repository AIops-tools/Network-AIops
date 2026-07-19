"""Dedicated ops-logic tests: WHICH NAPALM driver methods each op calls, the
config-diff/commit plumbing, undo before-state capture on writes, connection
timeout defaults, and NetBox query plumbing — all against mocked drivers.

Complements test_smoke.py (which checks value mapping against a rich fake
driver); here the assertions are on the *calls* made to the driver.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import network_aiops.connection as conn_mod
from network_aiops.config import TargetConfig
from network_aiops.ops import config_ops, facts, netbox_ops

TARGET = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


@pytest.fixture
def driver_cls(monkeypatch):
    """A MagicMock NAPALM driver class routed through connection._driver_for."""
    cls = MagicMock(name="driver_cls")
    dev = cls.return_value
    dev.get_facts.return_value = {
        "hostname": "core-sw1", "vendor": "Arista", "interface_list": ["Ethernet1"],
    }
    dev.get_interfaces.return_value = {"Ethernet1": {"is_up": True, "is_enabled": True}}
    dev.get_bgp_neighbors.return_value = {}
    dev.get_config.return_value = {"running": "hostname core-sw1\n"}
    dev.compare_config.return_value = "+ ntp server 10.0.0.99"
    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: cls)
    return cls


# ── Connection layer: session lifecycle + default timeout ──────────────


@pytest.mark.unit
def test_device_session_opens_and_always_closes(driver_cls):
    with conn_mod.device_session(TARGET) as dev:
        pass
    dev.open.assert_called_once()
    dev.close.assert_called_once()


@pytest.mark.unit
def test_device_session_applies_default_timeout(driver_cls):
    with conn_mod.device_session(TARGET):
        pass
    optional_args = driver_cls.call_args.kwargs["optional_args"]
    assert optional_args["timeout"] == 60  # line-wide default: no indefinite hangs


@pytest.mark.unit
def test_device_session_user_optional_args_win_over_defaults(driver_cls):
    target = TargetConfig(
        name="core-sw1", driver="eos", host="10.0.0.1", username="admin",
        optional_args={"timeout": 5, "transport": "ssh"},
    )
    with conn_mod.device_session(target):
        pass
    optional_args = driver_cls.call_args.kwargs["optional_args"]
    assert optional_args == {"timeout": 5, "transport": "ssh"}


# ── Read ops: the right getter is called ────────────────────────────────


@pytest.mark.unit
def test_device_facts_calls_get_facts(driver_cls):
    result = facts.device_facts(TARGET)
    driver_cls.return_value.get_facts.assert_called_once_with()
    assert result["hostname"] == "core-sw1"
    assert result["interface_count"] == 1


@pytest.mark.unit
def test_get_interfaces_calls_driver_getter(driver_cls):
    rows = facts.get_interfaces(TARGET)
    driver_cls.return_value.get_interfaces.assert_called_once_with()
    assert rows[0]["interface"] == "Ethernet1"


@pytest.mark.unit
def test_get_bgp_neighbors_calls_driver_getter(driver_cls):
    assert facts.get_bgp_neighbors(TARGET) == []
    driver_cls.return_value.get_bgp_neighbors.assert_called_once_with()


# ── Config plumbing: diff is dry-run, merge/replace commit + capture ────


@pytest.mark.unit
def test_config_diff_stages_compares_discards_never_commits(driver_cls):
    dev = driver_cls.return_value
    result = config_ops.config_diff(TARGET, "ntp server 10.0.0.99")
    dev.load_merge_candidate.assert_called_once_with(config="ntp server 10.0.0.99")
    dev.compare_config.assert_called_once()
    dev.discard_config.assert_called_once()
    dev.commit_config.assert_not_called()
    assert result["committed"] is False
    assert "ntp server" in result["diff"]


@pytest.mark.unit
def test_config_diff_replace_mode_uses_replace_candidate(driver_cls):
    dev = driver_cls.return_value
    result = config_ops.config_diff(TARGET, "hostname new\n", replace=True)
    dev.load_replace_candidate.assert_called_once_with(config="hostname new\n")
    dev.load_merge_candidate.assert_not_called()
    assert result["mode"] == "replace"


@pytest.mark.unit
def test_config_diff_discards_candidate_even_when_compare_fails(driver_cls):
    dev = driver_cls.return_value
    dev.compare_config.side_effect = RuntimeError("boom")
    with pytest.raises(conn_mod.NetworkApiError):
        config_ops.config_diff(TARGET, "ntp server 10.0.0.99")
    dev.discard_config.assert_called_once()  # candidate never left staged
    dev.commit_config.assert_not_called()


@pytest.mark.unit
def test_config_merge_captures_backup_before_commit(driver_cls):
    """The undo before-state (running config) must be read BEFORE the commit."""
    dev = driver_cls.return_value
    calls: list[str] = []
    dev.get_config.side_effect = lambda **kw: (
        calls.append("get_config"), {"running": "hostname old\n"})[1]
    dev.commit_config.side_effect = lambda: calls.append("commit_config")

    result = config_ops.config_merge(TARGET, "ntp server 10.0.0.99")
    dev.load_merge_candidate.assert_called_once_with(config="ntp server 10.0.0.99")
    assert calls == ["get_config", "commit_config"]
    assert result["backup"] == "hostname old\n"
    assert result["committed"] is True


@pytest.mark.unit
def test_config_replace_captures_backup_and_commits(driver_cls):
    dev = driver_cls.return_value
    result = config_ops.config_replace(TARGET, "hostname new\n")
    dev.load_replace_candidate.assert_called_once_with(config="hostname new\n")
    dev.commit_config.assert_called_once()
    assert result["backup"] == "hostname core-sw1\n"
    assert result["action"] == "replaced"


@pytest.mark.unit
def test_config_rollback_calls_driver_rollback(driver_cls):
    result = config_ops.config_rollback(TARGET)
    driver_cls.return_value.rollback.assert_called_once_with()
    assert result["action"] == "rolled_back"


# ── NetBox ops: query plumbing against a mocked pynetbox client ─────────


@pytest.mark.unit
def test_netbox_list_devices_passes_limit_and_name_filter():
    api = MagicMock()
    api.dcim.devices.filter.return_value = []
    netbox_ops.netbox_list_devices(api, limit=10, name="edge")
    api.dcim.devices.filter.assert_called_once_with(limit=11, name__ic="edge")


@pytest.mark.unit
def test_netbox_device_interfaces_filters_by_device():
    api = MagicMock()
    api.dcim.interfaces.filter.return_value = []
    netbox_ops.netbox_device_interfaces(api, "edge-1", limit=25)
    api.dcim.interfaces.filter.assert_called_once_with(device="edge-1", limit=26)


@pytest.mark.unit
def test_netbox_get_device_uses_exact_name():
    api = MagicMock()
    api.dcim.devices.get.return_value = None
    result = netbox_ops.netbox_get_device(api, "nope")
    api.dcim.devices.get.assert_called_once_with(name="nope")
    assert "not found" in result["error"]
