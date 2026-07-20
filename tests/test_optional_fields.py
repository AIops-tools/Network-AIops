"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. Collapsing the two hides information from any consumer, and a
smaller local model will confidently invent the difference. These tests pin the
contract end-to-end: helper, ops layer, and the CLI rendering that has to cope
with a null.

This matters more on a multi-vendor network fleet than almost anywhere else:
NAPALM normalises across Cisco IOS/NX-OS/IOS-XR, Arista EOS and Juniper Junos,
and which optional keys a getter actually populates varies by driver *and* by
platform. ``serial_number``, an interface ``description``, an LLDP neighbour's
``hostname`` — any of these can simply be absent. "" would say the switch has a
blank description; null says the driver never told us.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import network_aiops.connection as conn_mod
from network_aiops.config import TargetConfig
from network_aiops.governance import opt_str
from network_aiops.ops import facts, netbox_ops

runner = CliRunner()

TARGET = TargetConfig(name="core-sw1", driver="ios", host="10.0.0.1", username="admin")


@pytest.fixture
def bare_driver(monkeypatch):
    """A driver whose getters return only the keys the platform actually gave us."""
    cls = MagicMock(name="driver_cls")
    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: cls)
    return cls.return_value


# ── the helper itself ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("GigabitEthernet0/1", 64) == "GigabitEthernet0/1"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    # A cut announces itself: the ellipsis is the only signal a reader gets
    # that what they are looking at is not the whole value.
    assert opt_str("abcdef", 3) == "ab\u2026"
    assert opt_str("abc", 3) == "abc"  # exactly at the cap is not truncated


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(65001) == "65001"


# ── ops layer: NAPALM getters ───────────────────────────────────────────────


@pytest.mark.unit
def test_device_facts_report_absent_fields_as_none(bare_driver):
    """An IOS box that reports no serial/model must not claim an empty one."""
    bare_driver.get_facts.return_value = {"hostname": "core-sw1"}
    result = facts.device_facts(TARGET)
    assert result["hostname"] == "core-sw1"
    assert result["serial_number"] is None
    assert result["model"] is None
    assert result["vendor"] is None


@pytest.mark.unit
def test_device_facts_keep_empty_string_when_source_is_empty(bare_driver):
    """An explicitly empty upstream value is preserved as '' — not turned into null."""
    bare_driver.get_facts.return_value = {"hostname": "core-sw1", "serial_number": ""}
    assert facts.device_facts(TARGET)["serial_number"] == ""


@pytest.mark.unit
def test_device_facts_never_drop_the_key_itself(bare_driver):
    """Keys are always present; only their value may be null.

    Omitting a key entirely is worse than a null — the consumer cannot tell the
    field was even considered.
    """
    bare_driver.get_facts.return_value = {}
    row = facts.device_facts(TARGET)
    for key in ("name", "hostname", "fqdn", "vendor", "model", "os_version",
                "serial_number", "uptime_seconds", "interface_count"):
        assert key in row, f"{key} must be present even when the driver omitted it"


@pytest.mark.unit
def test_interface_description_absent_is_none(bare_driver):
    """A ge-0/0/0 with no configured description is not a blank description."""
    bare_driver.get_interfaces.return_value = {
        "ge-0/0/0": {"is_up": True, "is_enabled": True},
    }
    row = facts.get_interfaces(TARGET)[0]
    assert row["interface"] == "ge-0/0/0", "the interface name itself is always present"
    assert row["description"] is None
    assert row["mac_address"] is None


@pytest.mark.unit
def test_lldp_neighbor_without_hostname_reports_none(bare_driver):
    """LLDP often carries a chassis-id but no system name — say so, don't fake it."""
    bare_driver.get_lldp_neighbors.return_value = {"Ethernet1": [{"port": "Ethernet49"}]}
    row = facts.get_lldp_neighbors(TARGET)[0]
    assert row["local_port"] == "Ethernet1"
    assert row["remote_port"] == "Ethernet49"
    assert row["remote_host"] is None


@pytest.mark.unit
def test_netbox_device_summary_reports_absent_fields_as_none():
    """A NetBox device with no site/role/primary-IP assigned reports null."""
    device = MagicMock()
    device.name = "edge-1"
    device.role = None
    device.site = None
    device.status = None
    device.primary_ip = None
    api = MagicMock()
    api.dcim.devices.filter.return_value = [device]

    row = netbox_ops.netbox_list_devices(api)["devices"][0]
    assert row["name"] == "edge-1"
    assert row["role"] is None
    assert row["site"] is None
    assert row["primary_ip"] is None


# ── truncation envelope: a capped read announces itself ─────────────────────


@pytest.mark.unit
def test_netbox_list_devices_measures_truncation():
    """``truncated`` is measured from an extra fetched row, never guessed."""
    api = MagicMock()
    api.dcim.devices.filter.return_value = [MagicMock() for _ in range(4)]

    result = netbox_ops.netbox_list_devices(api, limit=3)
    api.dcim.devices.filter.assert_called_once_with(limit=4)
    assert result["returned"] == 3, "only `limit` rows are returned"
    assert len(result["devices"]) == 3
    assert result["limit"] == 3
    assert result["truncated"] is True


@pytest.mark.unit
def test_netbox_list_devices_exactly_at_the_limit_is_not_truncated():
    """A result whose length happens to equal the limit is NOT truncation."""
    api = MagicMock()
    api.dcim.devices.filter.return_value = [MagicMock() for _ in range(3)]
    result = netbox_ops.netbox_list_devices(api, limit=3)
    assert result["returned"] == 3
    assert result["truncated"] is False


@pytest.mark.unit
def test_netbox_device_interfaces_measures_truncation():
    api = MagicMock()
    api.dcim.interfaces.filter.return_value = [MagicMock() for _ in range(3)]

    result = netbox_ops.netbox_device_interfaces(api, "edge-1", limit=2)
    api.dcim.interfaces.filter.assert_called_once_with(device="edge-1", limit=3)
    assert result["returned"] == 2
    assert result["limit"] == 2
    assert result["truncated"] is True


# ── CLI rendering must survive a null ───────────────────────────────────────


@pytest.mark.unit
def test_cli_renders_rows_with_null_fields(monkeypatch, bare_driver):
    """The table must survive a null field rather than crashing on render."""
    import network_aiops.cli.device as cli_device

    bare_driver.get_interfaces.return_value = {
        "GigabitEthernet0/1": {"is_up": True, "is_enabled": True},
    }
    monkeypatch.setattr(cli_device, "_resolve", lambda target=None: TARGET)

    from network_aiops.cli import app

    result = runner.invoke(app, ["device", "interfaces"])
    assert result.exit_code == 0, result.output
    assert "GigabitEthernet0/1" in result.output
    assert "None" not in result.output, "a null must not render as the word 'None'"


@pytest.mark.unit
def test_cli_announces_a_truncated_netbox_listing(monkeypatch):
    """A capped listing says so, instead of looking like the whole estate."""
    import network_aiops.cli.netbox as cli_netbox

    device = MagicMock()
    device.name = "edge-1"
    api = MagicMock()
    api.dcim.devices.filter.return_value = [device, MagicMock()]
    monkeypatch.setattr(cli_netbox, "get_manager", lambda: MagicMock(netbox=lambda: api))

    from network_aiops.cli import app

    result = runner.invoke(app, ["netbox", "list", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "truncated" in result.output


@pytest.mark.unit
def test_undo_list_envelope_measures_truncation(monkeypatch):
    from mcp_server.tools import undo as undo_tools

    rows = [
        {
            "undo_id": f"u{i}",
            "ts": "2026-07-18T00:00:00Z",
            "tool": "some_tool",
            "undo_tool": "some_inverse_tool",
            "note": "",
        }
        for i in range(4)
    ]
    captured = {}

    class _Store:
        def list(self, *, status=None, limit=50):
            captured["limit"] = limit
            return rows[:limit]

    monkeypatch.setattr(undo_tools, "get_undo_store", lambda: _Store())
    result = undo_tools.undo_list(limit=3)
    assert captured["limit"] == 4, "one extra row is fetched to measure truncation"
    assert result["returned"] == 3
    assert result["limit"] == 3
    assert result["truncated"] is True
    assert len(result["undos"]) == 3
