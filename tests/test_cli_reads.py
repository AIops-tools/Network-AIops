"""CLI read-command tests: drive ``network-aiops device/config/netbox`` through a
Typer CliRunner against a mocked NAPALM driver (and mocked NetBox client). These
exercise the rich-table rendering paths and the dry-run config previews (no
commit, no governance), plus the ``cli_errors`` teaching-error translation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def device_cli(monkeypatch, eos_target, fake_driver_cls):
    """Route the device + config CLI target resolution to the fake device."""
    import network_aiops.cli.config as cli_config
    import network_aiops.cli.device as cli_device
    from mcp_server.tools import config_ops as gov

    monkeypatch.setattr(cli_device, "_resolve", lambda target=None: eos_target)
    monkeypatch.setattr(cli_config, "_resolve", lambda target=None: eos_target)
    # The config CLI routes BOTH its dry-run and its real path through the
    # governed twin, which resolves the target itself.
    monkeypatch.setattr(gov, "_target", lambda name=None: eos_target)
    return eos_target


def _app():
    from network_aiops.cli import app

    return app


# ── device read commands render their tables/lines ──────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["device", "facts"], "core-sw1"),
        (["device", "interfaces"], "Ethernet1"),
        (["device", "bgp"], "65001"),
        (["device", "lldp"], "core-sw2"),
        (["device", "arp"], "10.0.0.2"),
        (["device", "counters"], "Ethernet1"),
        (["device", "mac"], "Ethernet1"),
        (["device", "vlans"], "users"),
        (["device", "environment"], "Environment"),
        (["device", "health"], "core-sw1"),
    ],
)
def test_device_read_commands_render(device_cli, argv, expected):
    result = runner.invoke(_app(), argv)
    assert result.exit_code == 0, result.output
    assert expected in result.output


@pytest.mark.unit
def test_device_route_command_passes_destination(device_cli):
    result = runner.invoke(_app(), ["device", "route", "10.0.0.0/24"])
    assert result.exit_code == 0, result.output
    assert "10.0.0.0/24" in result.output


@pytest.mark.unit
def test_device_health_shows_issues_when_unhealthy(monkeypatch, eos_target):
    """Ethernet2 enabled-but-down → the health command prints an ISSUES status."""
    import network_aiops.cli.device as cli_device
    import network_aiops.connection as conn_mod
    from tests.conftest import FakeDriver

    monkeypatch.setattr(conn_mod, "_driver_for", lambda t: FakeDriver)
    monkeypatch.setattr(cli_device, "_resolve", lambda target=None: eos_target)
    result = runner.invoke(_app(), ["device", "health"])
    assert result.exit_code == 0, result.output
    assert "ISSUES" in result.output


# ── cli_errors: a NetworkApiError becomes one red line + exit 1 ─────────────


@pytest.mark.unit
def test_device_command_translates_error(monkeypatch, eos_target):
    import network_aiops.cli.device as cli_device
    from network_aiops.connection import NetworkApiError

    def _boom(target=None):
        raise NetworkApiError("could not connect to core-sw1")

    monkeypatch.setattr(cli_device, "_resolve", _boom)
    result = runner.invoke(_app(), ["device", "facts"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "could not connect" in result.output


# ── config read + dry-run previews (no commit, no governance) ───────────────


@pytest.mark.unit
def test_config_backup_prints_running(device_cli):
    result = runner.invoke(_app(), ["config", "backup"])
    assert result.exit_code == 0, result.output
    assert "hostname core-sw1" in result.output


@pytest.mark.unit
def test_config_backup_writes_to_file(device_cli, tmp_path):
    out = tmp_path / "running.cfg"
    result = runner.invoke(_app(), ["config", "backup", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text() == "hostname core-sw1\n"
    assert "Saved running config" in result.output


@pytest.mark.unit
def test_config_diff_dry_run(device_cli, tmp_path):
    snippet = tmp_path / "snippet.cfg"
    snippet.write_text("ntp server 10.0.0.99")
    result = runner.invoke(_app(), ["config", "diff", str(snippet)])
    assert result.exit_code == 0, result.output
    assert "not committed" in result.output
    assert "ntp server" in result.output


@pytest.mark.unit
def test_config_merge_dry_run_does_not_commit(device_cli, tmp_path):
    snippet = tmp_path / "snippet.cfg"
    snippet.write_text("ntp server 10.0.0.99")
    result = runner.invoke(_app(), ["config", "merge", str(snippet), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "Committed" not in result.output


@pytest.mark.unit
def test_config_replace_dry_run_does_not_commit(device_cli, tmp_path):
    snippet = tmp_path / "full.cfg"
    snippet.write_text("hostname new\n")
    result = runner.invoke(_app(), ["config", "replace", str(snippet), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "Committed" not in result.output


# ── netbox CLI against a mocked pynetbox client ─────────────────────────────


@pytest.fixture
def netbox_cli(monkeypatch):
    import network_aiops.cli.netbox as cli_netbox

    api = MagicMock()
    mgr = MagicMock()
    mgr.netbox.return_value = api
    monkeypatch.setattr(cli_netbox, "get_manager", lambda: mgr)
    return api


@pytest.mark.unit
def test_netbox_list_command(netbox_cli):
    dev = MagicMock()
    dev.name = "edge-1"
    dev.role.name = "edge"
    dev.site.name = "dc1"
    dev.status.value = "active"
    dev.primary_ip.address = "10.0.0.5/32"
    netbox_cli.dcim.devices.filter.return_value = [dev]

    result = runner.invoke(_app(), ["netbox", "list", "--name", "edge"])
    assert result.exit_code == 0, result.output
    assert "edge-1" in result.output


@pytest.mark.unit
def test_netbox_get_command(netbox_cli):
    dev = MagicMock()
    dev.name = "edge-1"
    dev.role.name = "edge"
    dev.site.name = "dc1"
    dev.status.value = "active"
    dev.primary_ip.address = "10.0.0.5/32"
    dev.device_type.model = "DCS-7050"
    dev.serial = "SER123"
    netbox_cli.dcim.devices.get.return_value = dev

    result = runner.invoke(_app(), ["netbox", "get", "edge-1"])
    assert result.exit_code == 0, result.output
    assert "DCS-7050" in result.output


@pytest.mark.unit
def test_netbox_interfaces_command(netbox_cli):
    iface = MagicMock()
    iface.name = "Ethernet1"
    iface.type.value = "10gbase-x-sfpp"
    iface.enabled = True
    iface.description = "uplink"
    iface.mac_address = "00:11:22:33:44:55"
    netbox_cli.dcim.interfaces.filter.return_value = [iface]

    result = runner.invoke(_app(), ["netbox", "interfaces", "edge-1"])
    assert result.exit_code == 0, result.output
    assert "Ethernet1" in result.output


@pytest.mark.unit
def test_netbox_command_translates_unconfigured_error(monkeypatch):
    import network_aiops.cli.netbox as cli_netbox
    from network_aiops.connection import NetworkApiError

    mgr = MagicMock()
    mgr.netbox.side_effect = NetworkApiError("NetBox is not configured")
    monkeypatch.setattr(cli_netbox, "get_manager", lambda: mgr)
    result = runner.invoke(_app(), ["netbox", "list"])
    assert result.exit_code == 1
    assert "not configured" in result.output
