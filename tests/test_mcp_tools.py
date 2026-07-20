"""MCP governed-twin tests: drive each ``@governed_tool`` in mcp_server/tools/*
against a mocked NAPALM driver (and mocked NetBox client) on an isolated
governance home. These assert the governed wrapper actually reaches the op and
returns the mapped payload (and, for reads, does NOT return an error dict), plus
the config write/undo loop through the real undo store.
"""

from __future__ import annotations

import sqlite3

import pytest

from mcp_server.tools import config_ops as config_tools
from mcp_server.tools import environment as env_tools
from mcp_server.tools import facts as facts_tools
from mcp_server.tools import health as health_tools
from mcp_server.tools import inventory as inv_tools
from mcp_server.tools import neighbors as nbr_tools
from mcp_server.tools import netbox as netbox_tools


@pytest.fixture
def target_read(monkeypatch, eos_target, fake_driver_cls):
    """Point every read-tool module's ``_target`` at the fake device."""
    for mod in (facts_tools, env_tools, inv_tools, nbr_tools,
                health_tools, config_tools):
        monkeypatch.setattr(mod, "_target", lambda name=None: eos_target)
    return eos_target


# ── facts / neighbors / inventory / environment / health read twins ─────────


@pytest.mark.unit
def test_governed_device_facts_returns_payload_not_error(gov_home, target_read):
    result = facts_tools.device_facts()
    assert "error" not in result
    assert result["vendor"] == "Arista"
    assert result["interface_count"] == 2


@pytest.mark.unit
def test_governed_get_interfaces_ip_twin(gov_home, target_read):
    rows = facts_tools.get_interfaces_ip()
    assert any(r["address"] == "10.0.0.1" for r in rows)


@pytest.mark.unit
def test_governed_read_list_twins_map_cleanly(gov_home, target_read):
    assert facts_tools.get_interfaces()[0]["interface"] == "Ethernet1"
    assert facts_tools.get_bgp_neighbors()[0]["remote_as"] == 65001
    assert facts_tools.get_lldp_neighbors()[0]["remote_host"] == "core-sw2"
    assert facts_tools.get_arp_table()[0]["ip"] == "10.0.0.2"
    assert nbr_tools.get_bgp_neighbors_detail()[0]["connection_state"] == "Established"
    assert nbr_tools.get_lldp_neighbors_detail()[0]["remote_system_name"] == "core-sw2"
    assert inv_tools.get_interfaces_counters()[0]["rx_errors"] == 1
    assert inv_tools.get_mac_address_table()[0]["vlan"] == 10
    assert inv_tools.get_vlans()[0]["name"] == "users"
    assert inv_tools.get_route_to("10.0.0.0/24")[0]["next_hop"] == "10.0.0.2"


@pytest.mark.unit
def test_governed_environment_twins(gov_home, target_read):
    env = env_tools.get_environment()
    assert env["memory"]["available_ram"] == 1000000
    assert env_tools.get_optics()[0]["input_power"] == -3.0
    assert env_tools.get_ntp_servers() == ["10.0.0.99"]
    assert env_tools.get_ntp_stats()[0]["synchronized"] is True
    # secrets never surface through the governed twin either
    users = env_tools.get_users()
    assert users[0]["has_password"] is True and "password" not in users[0]
    assert env_tools.get_snmp_information()["community_count"] == 1
    assert env_tools.get_network_instances()[0]["name"] == "MGMT"


@pytest.mark.unit
def test_governed_device_health_twin(gov_home, target_read):
    h = health_tools.device_health()
    assert h["hostname"] == "core-sw1"
    assert h["interfaces"]["total"] == 2


# ── config read/dry-run twins + the write→undo loop ─────────────────────────


@pytest.mark.unit
def test_governed_config_backup_and_diff(gov_home, target_read):
    assert config_tools.config_backup()["config"] == "hostname core-sw1\n"
    diff = config_tools.config_diff(config_text="ntp server 10.0.0.99")
    assert diff["committed"] is False
    assert "ntp server" in diff["diff"]


@pytest.mark.unit
def test_governed_config_rollback_twin(gov_home, target_read, fake_driver_cls):
    result = config_tools.config_rollback()
    assert result["action"] == "rolled_back"
    # audit row landed in the isolated home
    conn = sqlite3.connect(gov_home / "audit.db")
    try:
        tools = [r[0] for r in conn.execute("SELECT tool FROM audit_log")]
    finally:
        conn.close()
    assert "config_rollback" in tools


@pytest.mark.unit
def test_governed_config_merge_records_undo_and_apply_previews(gov_home, target_read):
    """End-to-end: governed merge records a real undo token; undo_apply dry-run
    previews the inverse (config_replace back to the captured backup)."""
    from mcp_server.tools import undo as undo_tools

    result = config_tools.config_merge(config_text="ntp server 10.0.0.99")
    assert result["committed"] is True
    undo_id = result["_undo_id"]

    listed = undo_tools.undo_list()
    ids = {u["undoId"] for u in listed["undos"]}
    assert undo_id in ids
    row = next(u for u in listed["undos"] if u["undoId"] == undo_id)
    assert row["inverseTool"] == "config_replace"

    preview = undo_tools.undo_apply(undo_id=undo_id, dry_run=True)
    assert preview["dryRun"] is True
    assert preview["wouldApply"]["tool"] == "config_replace"
    # The inverse replays the RAW captured config, which never appeared in the
    # result — the caller only ever saw its digest.
    assert preview["wouldApply"]["params"]["config_text"] == "hostname core-sw1\n"
    assert result["backup"]["retainedForUndo"] is True


# ── netbox twins against a mocked client ────────────────────────────────────


@pytest.fixture
def netbox_api(monkeypatch):
    from unittest.mock import MagicMock

    api = MagicMock()
    monkeypatch.setattr(netbox_tools, "_netbox", lambda: api)
    return api


@pytest.mark.unit
def test_governed_netbox_list_devices(gov_home, netbox_api):
    dev = __import__("unittest").mock.MagicMock()
    dev.name = "edge-1"
    dev.role.name = "edge"
    dev.site.name = "dc1"
    dev.status.value = "active"
    dev.primary_ip.address = "10.0.0.5/32"
    netbox_api.dcim.devices.filter.return_value = [dev]

    result = netbox_tools.netbox_list_devices(name="edge", limit=10)
    # limit + 1 is requested so "truncated" is measured, not guessed
    netbox_api.dcim.devices.filter.assert_called_once_with(limit=11, name__ic="edge")
    assert result["devices"][0]["name"] == "edge-1"
    assert result["returned"] == 1
    assert result["limit"] == 10
    assert result["truncated"] is False


@pytest.mark.unit
def test_governed_netbox_get_device_missing_returns_error_payload(gov_home, netbox_api):
    netbox_api.dcim.devices.get.return_value = None
    out = netbox_tools.netbox_get_device(name="nope")
    assert "not found" in out["error"]


@pytest.mark.unit
def test_governed_netbox_device_interfaces(gov_home, netbox_api):
    iface = __import__("unittest").mock.MagicMock()
    iface.name = "Ethernet1"
    iface.type.value = "10gbase-x-sfpp"
    iface.enabled = True
    iface.description = "uplink"
    iface.mac_address = "00:11:22:33:44:55"
    netbox_api.dcim.interfaces.filter.return_value = [iface]

    result = netbox_tools.netbox_device_interfaces(device="edge-1", limit=25)
    netbox_api.dcim.interfaces.filter.assert_called_once_with(device="edge-1", limit=26)
    assert result["interfaces"][0]["name"] == "Ethernet1"
    assert result["truncated"] is False


@pytest.mark.unit
def test_governed_tool_error_path_returns_safe_dict(gov_home, monkeypatch, eos_target):
    """When the op raises, the governed twin returns a sanitised error dict with a
    doctor hint — never a raw traceback."""
    from network_aiops.connection import NetworkApiError

    def _boom(name=None):
        raise NetworkApiError("device unreachable")

    monkeypatch.setattr(facts_tools, "_target", _boom)
    out = facts_tools.device_facts()
    assert "error" in out
    assert "doctor" in out["hint"]
