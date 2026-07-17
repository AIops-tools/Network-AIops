"""Ops-layer tests for the getters/plumbing not covered by test_ops/test_smoke:
per-interface IP mapping, LLDP mapping, config_backup, the health issue-detection
branches, and the NetBox device found/interface-mapping paths — all against a
mocked NAPALM driver / mocked pynetbox client. Assertions are on WHICH driver
getter runs and how its raw shape is flattened, not on filler.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from network_aiops.ops import config_ops, environment, facts, health, netbox_ops

# ── facts: the two getters test_smoke skips (IP + LLDP) ─────────────────────


@pytest.mark.unit
def test_get_interfaces_ip_flattens_families_and_addresses(fake_driver_cls, eos_target):
    rows = facts.get_interfaces_ip(eos_target)
    # calls the get_interfaces_ip getter (not get_interfaces)
    by_family = {(r["interface"], r["family"]): r for r in rows}
    assert by_family[("Ethernet1", "ipv4")]["address"] == "10.0.0.1"
    assert by_family[("Ethernet1", "ipv4")]["prefix_length"] == 24
    assert by_family[("Ethernet1", "ipv6")]["address"] == "2001:db8::1"
    assert by_family[("Ethernet1", "ipv6")]["prefix_length"] == 64


@pytest.mark.unit
def test_get_interfaces_ip_calls_correct_getter(eos_target, monkeypatch):
    import network_aiops.connection as conn_mod

    dev = MagicMock()
    dev.get_interfaces_ip.return_value = {}
    cls = MagicMock(return_value=dev)
    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: cls)

    assert facts.get_interfaces_ip(eos_target) == []
    dev.get_interfaces_ip.assert_called_once_with()


@pytest.mark.unit
def test_get_lldp_neighbors_maps_local_and_remote(fake_driver_cls, eos_target):
    rows = facts.get_lldp_neighbors(eos_target)
    assert rows[0]["local_port"] == "Ethernet1"
    assert rows[0]["remote_host"] == "core-sw2"
    assert rows[0]["remote_port"] == "Ethernet1"


# ── config_backup: reads running config, adds a save-hint note ──────────────


@pytest.mark.unit
def test_config_backup_returns_running_and_note(fake_driver_cls, eos_target):
    result = config_ops.config_backup(eos_target)
    assert result["config"] == "hostname core-sw1\n"
    assert "-o" in result["note"]
    assert result["name"] == "core-sw1"


@pytest.mark.unit
def test_config_backup_handles_non_dict_config(eos_target, monkeypatch):
    """_running_config tolerates a driver returning a bare string, not a dict."""
    import network_aiops.connection as conn_mod

    dev = MagicMock()
    dev.get_config.return_value = "raw running config text"
    cls = MagicMock(return_value=dev)
    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: cls)

    result = config_ops.config_backup(eos_target)
    assert result["config"] == "raw running config text"


# ── health: the issue-detection branches (fans/power/temp) ──────────────────


def _target():
    from network_aiops.config import TargetConfig

    return TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


@pytest.mark.unit
def test_device_health_flags_enabled_but_down_interface(fake_driver_cls, eos_target):
    """Ethernet2 is enabled but down in the fake → an issue, unhealthy."""
    h = health.device_health(eos_target)
    assert h["interfaces"]["enabled_but_down"] == 1
    assert any("enabled interface" in i for i in h["issues"])
    assert h["healthy"] is False


@pytest.mark.unit
def test_device_health_flags_fan_power_and_temperature(monkeypatch):
    import network_aiops.connection as conn_mod
    from tests.conftest import FakeDriver

    class Bad(FakeDriver):
        def get_environment(self):
            return {
                "fans": {"Fan1": {"status": False}},          # fan down
                "power": {"PSU1": {"status": False}},          # psu down
                "temperature": {"s1": {"temperature": 95.0, "is_alert": True,
                                       "is_critical": False}},  # temp alert
                "cpu": {}, "memory": {},
            }

        def get_interfaces(self):
            return {"Ethernet1": {"is_up": True, "is_enabled": True}}

    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: Bad)
    h = health.device_health(_target())
    joined = " ".join(h["issues"])
    assert "fans are not OK" in joined
    assert "power supplies are not OK" in joined
    assert "temperature sensor" in joined
    assert h["healthy"] is False


# ── netbox_ops: the device-found path + interface mapping ───────────────────


@pytest.mark.unit
def test_netbox_get_device_found_adds_type_and_serial():
    api = MagicMock()
    dev = MagicMock()
    dev.name = "edge-1"
    dev.role.name = "edge"
    dev.site.name = "dc1"
    dev.status.value = "active"
    dev.primary_ip.address = "10.0.0.5/32"
    dev.device_type.model = "DCS-7050"
    dev.serial = "SER123"
    api.dcim.devices.get.return_value = dev

    out = netbox_ops.netbox_get_device(api, "edge-1")
    api.dcim.devices.get.assert_called_once_with(name="edge-1")
    assert out["name"] == "edge-1"
    assert out["device_type"] == "DCS-7050"
    assert out["serial"] == "SER123"
    assert "error" not in out


@pytest.mark.unit
def test_netbox_device_interfaces_maps_fields():
    api = MagicMock()
    iface = MagicMock()
    iface.name = "Ethernet1"
    iface.type.value = "10gbase-x-sfpp"
    iface.enabled = True
    iface.description = "uplink"
    iface.mac_address = "00:11:22:33:44:55"
    api.dcim.interfaces.filter.return_value = [iface]

    rows = netbox_ops.netbox_device_interfaces(api, "edge-1", limit=10)
    api.dcim.interfaces.filter.assert_called_once_with(device="edge-1", limit=10)
    assert rows[0]["type"] == "10gbase-x-sfpp"
    assert rows[0]["enabled"] is True
    assert rows[0]["mac_address"] == "00:11:22:33:44:55"


@pytest.mark.unit
def test_netbox_list_devices_clamps_limit_to_minimum_one():
    api = MagicMock()
    api.dcim.devices.filter.return_value = []
    netbox_ops.netbox_list_devices(api, limit=0)
    # limit is clamped to >= 1 so a 0/negative page size never reaches NetBox
    assert api.dcim.devices.filter.call_args.kwargs["limit"] == 1


# ── environment getters not asserted in smoke (optics empty, ntp/vrf shapes) ─


@pytest.mark.unit
def test_get_optics_maps_channel_state(fake_driver_cls, eos_target):
    rows = environment.get_optics(eos_target)
    assert rows[0]["input_power"] == -3.0
    assert rows[0]["output_power"] == -2.0
    assert rows[0]["laser_bias_current"] == 30.0


@pytest.mark.unit
def test_get_network_instances_reads_rd_and_interfaces(fake_driver_cls, eos_target):
    rows = environment.get_network_instances(eos_target)
    assert rows[0]["route_distinguisher"] == "65000:1"
    assert rows[0]["interfaces"] == ["Ethernet1"]
