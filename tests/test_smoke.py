"""Smoke tests for the network-aiops skeleton.

Proves: every module imports, the CLI Typer app builds and --help works (root
and leaf), the MCP server exposes the expected tools, EVERY MCP tool carries the
network-aiops harness marker ``_is_governed_tool``, write tools record undo
descriptors via the harness, and ops work against a MOCKED napalm driver (and a
mocked pynetbox) — no real device needed.
"""

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # facts (read)
    "device_facts", "get_interfaces", "get_interfaces_ip", "get_bgp_neighbors",
    "get_lldp_neighbors", "get_arp_table",
    # config (read)
    "config_backup", "config_diff",
    # config (write)
    "config_merge", "config_replace", "config_rollback",
    # netbox (read)
    "netbox_list_devices", "netbox_get_device",
}

WRITE_TOOLS_WITH_UNDO = {"config_merge", "config_replace"}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "network_aiops",
        "network_aiops.config",
        "network_aiops.connection",
        "network_aiops.doctor",
        "network_aiops.ops._shared",
        "network_aiops.ops.facts",
        "network_aiops.ops.config_ops",
        "network_aiops.ops.netbox_ops",
        "network_aiops.cli",
        "network_aiops.cli._root",
        "network_aiops.cli._common",
        "network_aiops.cli.device",
        "network_aiops.cli.config",
        "network_aiops.cli.netbox",
        "network_aiops.cli.doctor",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.facts",
        "mcp_server.tools.config_ops",
        "mcp_server.tools.netbox",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version():
    import network_aiops

    assert network_aiops.__version__ == "0.1.0"


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from network_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("device", "config", "netbox", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    """Recurse into leaf commands so any broken lazy import surfaces."""
    from network_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["device", "--help"], ["config", "--help"], ["netbox", "--help"],
        ["doctor", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
    for cmd in (
        ["device", "facts", "--help"], ["device", "interfaces", "--help"],
        ["device", "bgp", "--help"], ["device", "lldp", "--help"],
        ["device", "arp", "--help"],
        ["config", "backup", "--help"], ["config", "diff", "--help"],
        ["config", "merge", "--help"], ["config", "replace", "--help"],
        ["config", "rollback", "--help"],
        ["netbox", "list", "--help"], ["netbox", "get", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    """Every registered tool callable must carry the @governed_tool marker."""
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), (
            f"{name} is not wrapped with @governed_tool (harness marker missing)"
        )


# ── Fake NAPALM driver ──────────────────────────────────────────────────


class _FakeDriver:
    """Minimal NAPALM driver double covering the getters/config calls used."""

    def __init__(self, hostname=None, username=None, password=None, optional_args=None):
        self.hostname = hostname
        self.committed = False

    def open(self):
        return None

    def close(self):
        return None

    def get_facts(self):
        return {
            "hostname": "core-sw1",
            "fqdn": "core-sw1.lab",
            "vendor": "Arista",
            "model": "DCS-7050",
            "os_version": "4.30.1F",
            "serial_number": "ABC123",
            "uptime": 123456,
            "interface_list": ["Ethernet1", "Ethernet2"],
        }

    def get_interfaces(self):
        return {
            "Ethernet1": {
                "is_up": True, "is_enabled": True, "speed": 10000,
                "description": "uplink", "mac_address": "00:11:22:33:44:55",
            }
        }

    def get_interfaces_ip(self):
        return {"Ethernet1": {"ipv4": {"10.0.0.1": {"prefix_length": 24}}}}

    def get_bgp_neighbors(self):
        return {
            "global": {
                "peers": {
                    "10.0.0.2": {
                        "remote_as": 65001, "is_up": True, "is_enabled": True,
                        "address_family": {"ipv4": {
                            "received_prefixes": 10, "accepted_prefixes": 10,
                        }},
                    }
                }
            }
        }

    def get_lldp_neighbors(self):
        return {"Ethernet1": [{"hostname": "core-sw2", "port": "Ethernet1"}]}

    def get_arp_table(self):
        return [{"interface": "Ethernet1", "ip": "10.0.0.2",
                 "mac": "00:aa:bb:cc:dd:ee", "age": 12.0}]

    def get_config(self, retrieve="running"):
        return {"running": "hostname core-sw1\n", "startup": "", "candidate": ""}

    def load_merge_candidate(self, config=None):
        self._candidate = config

    def load_replace_candidate(self, config=None):
        self._candidate = config

    def compare_config(self):
        return "+ ntp server 10.0.0.99"

    def discard_config(self):
        self._candidate = None

    def commit_config(self):
        self.committed = True

    def rollback(self):
        self.committed = False


def _patch_napalm(monkeypatch):
    """Make connection._driver_for return the fake driver class."""
    import network_aiops.connection as conn_mod

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: _FakeDriver)


@pytest.mark.unit
def test_facts_use_mocked_napalm_driver(monkeypatch):
    _patch_napalm(monkeypatch)
    from network_aiops.config import TargetConfig
    from network_aiops.ops import facts as ops

    target = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    f = ops.device_facts(target)
    assert f["vendor"] == "Arista"
    assert f["interface_count"] == 2

    ifaces = ops.get_interfaces(target)
    assert ifaces[0]["interface"] == "Ethernet1"
    assert ifaces[0]["is_up"] is True

    bgp = ops.get_bgp_neighbors(target)
    assert bgp[0]["remote_as"] == 65001
    assert ops.get_arp_table(target)[0]["ip"] == "10.0.0.2"


@pytest.mark.unit
def test_config_diff_is_dry_run(monkeypatch):
    """config_diff returns the diff and never commits."""
    _patch_napalm(monkeypatch)
    from network_aiops.config import TargetConfig
    from network_aiops.ops import config_ops as ops

    target = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    result = ops.config_diff(target, "ntp server 10.0.0.99")
    assert result["committed"] is False
    assert "ntp server" in result["diff"]


@pytest.mark.unit
def test_config_merge_records_replace_to_backup_undo(monkeypatch):
    """config_merge records a config_replace-to-backup inverse with _undo_id."""
    import network_aiops.governance.undo as undo_mod
    from mcp_server.tools import config_ops as cfg_tools
    from network_aiops.config import TargetConfig

    _patch_napalm(monkeypatch)
    target = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: target)

    recorded = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params):
            recorded["descriptor"] = undo_descriptor
            return "undo-1"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    result = cfg_tools.config_merge(config_text="ntp server 10.0.0.99", target="core-sw1")
    assert "error" not in result
    assert result["committed"] is True
    assert recorded["descriptor"]["tool"] == "config_replace"
    assert recorded["descriptor"]["params"]["config_text"] == result["backup"]
    assert recorded["descriptor"]["skill"] == "network-aiops"
    assert result.get("_undo_id") == "undo-1"


@pytest.mark.unit
def test_config_replace_records_undo(monkeypatch):
    """config_replace (high risk) records a restore-to-backup inverse."""
    import network_aiops.governance.undo as undo_mod
    from mcp_server.tools import config_ops as cfg_tools
    from network_aiops.config import TargetConfig

    _patch_napalm(monkeypatch)
    target = TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    monkeypatch.setattr(cfg_tools, "_target", lambda name=None: target)

    recorded = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params):
            recorded["descriptor"] = undo_descriptor
            return "undo-2"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    result = cfg_tools.config_replace(config_text="hostname new\n", target="core-sw1")
    assert "error" not in result
    assert recorded["descriptor"]["tool"] == "config_replace"
    assert recorded["descriptor"]["params"]["config_text"] == result["backup"]


@pytest.mark.unit
def test_connection_translates_errors():
    """NAPALM-style exceptions translate to a teaching NetworkApiError."""
    from network_aiops.config import TargetConfig
    from network_aiops.connection import NetworkApiError, _translate

    target = TargetConfig(name="r1", driver="ios", host="1.2.3.4", username="admin")

    # NAPALM's real class is named ConnectionException; _translate matches on
    # type(exc).__name__, so build a type with that exact name dynamically.
    conn_exc = type("ConnectionException", (Exception,), {})

    err = _translate(conn_exc("auth failed"), target)
    assert isinstance(err, NetworkApiError)
    assert "1.2.3.4" in str(err)

    err2 = _translate(NotImplementedError("no getter"), target)
    assert "not supported" in str(err2).lower()


@pytest.mark.unit
def test_unsupported_driver_is_rejected():
    """A non-supported driver yields a teaching NetworkApiError pointing to GitHub."""
    import network_aiops.connection as conn_mod
    from network_aiops.config import TargetConfig
    from network_aiops.connection import NetworkApiError

    target = TargetConfig(name="nokia1", driver="sros", host="1.1.1.1", username="admin")
    with pytest.raises(NetworkApiError) as exc:
        conn_mod._driver_for(target)
    assert "GitHub" in str(exc.value)


@pytest.mark.unit
def test_netbox_ops_with_mocked_pynetbox():
    """netbox_list_devices works against a mocked pynetbox client."""
    from network_aiops.ops import netbox_ops as ops

    dev = MagicMock()
    dev.name = "edge-1"
    dev.role.name = "edge"
    dev.site.name = "dc1"
    dev.status.value = "active"
    dev.primary_ip.address = "10.0.0.5/32"

    api = MagicMock()
    api.dcim.devices.filter.return_value = [dev]
    rows = ops.netbox_list_devices(api, name="edge")
    assert rows[0]["name"] == "edge-1"
    assert rows[0]["site"] == "dc1"

    api.dcim.devices.get.return_value = None
    miss = ops.netbox_get_device(api, "nope")
    assert "not found" in miss["error"]


@pytest.mark.unit
def test_netbox_degrades_gracefully_when_unconfigured():
    """netbox_api raises a teaching error when NetBox is not configured."""
    from network_aiops.connection import NetworkApiError, netbox_api

    with pytest.raises(NetworkApiError) as exc:
        netbox_api(None)
    assert "not configured" in str(exc.value).lower()
