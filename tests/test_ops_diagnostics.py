"""Unit tests for the pure diagnostics/RCA heuristics + the MCP tool wiring.

The heuristics in ``network_aiops.ops.diagnostics`` are pure functions over
already-normalized getter rows, so every threshold trip is exercised with plain
dicts (no device). Two extra tests drive the MCP tools against a mocked NAPALM
driver to prove collection + governance wiring.
"""

import pytest

from network_aiops.ops import diagnostics as diag

# ── interface_health_findings ────────────────────────────────────────────


@pytest.mark.unit
def test_interface_admin_up_oper_down_is_critical():
    ifaces = [{"interface": "Eth1", "is_up": False, "is_enabled": True}]
    result = diag.interface_health_findings(ifaces, [])
    assert result["interfacesAnalyzed"] == 1
    f = result["findings"][0]
    assert f["severity"] == "critical"
    assert f["signal"] == "interface down"
    assert f["entity"] == "Eth1"
    assert "is_up=False" in f["detail"]


@pytest.mark.unit
def test_interface_error_counters_trip_warning_and_cite_value():
    ifaces = [{"interface": "Eth1", "is_up": True, "is_enabled": True}]
    counters = [{"interface": "Eth1", "rx_errors": 80, "tx_errors": 40}]
    findings = diag.interface_health_findings(ifaces, counters)["findings"]
    errs = [f for f in findings if f["signal"] == "interface errors"]
    assert len(errs) == 1
    assert "120" in errs[0]["detail"]  # 80 + 40, cited
    assert errs[0]["severity"] == "warning"


@pytest.mark.unit
def test_interface_discards_trip_warning():
    ifaces = [{"interface": "Eth1", "is_up": True, "is_enabled": True}]
    counters = [{"interface": "Eth1", "rx_discards": 150, "tx_discards": 0}]
    findings = diag.interface_health_findings(ifaces, counters)["findings"]
    assert any(f["signal"] == "interface discards" and "150" in f["detail"] for f in findings)


@pytest.mark.unit
def test_interface_recent_flap_flagged_but_old_flap_ignored():
    recent = [{"interface": "Eth1", "is_up": True, "is_enabled": True, "last_flapped": 30.0}]
    old = [{"interface": "Eth2", "is_up": True, "is_enabled": True, "last_flapped": 99999.0}]
    unknown = [{"interface": "Eth3", "is_up": True, "is_enabled": True, "last_flapped": -1.0}]
    assert any(
        f["signal"] == "interface flapped"
        for f in diag.interface_health_findings(recent, [])["findings"]
    )
    assert diag.interface_health_findings(old, [])["findings"] == []
    assert diag.interface_health_findings(unknown, [])["findings"] == []


@pytest.mark.unit
def test_interface_healthy_is_clean():
    ifaces = [{"interface": "Eth1", "is_up": True, "is_enabled": True, "last_flapped": -1.0}]
    counters = [
        {"interface": "Eth1", "rx_errors": 0, "tx_errors": 0, "rx_discards": 0, "tx_discards": 0}
    ]
    assert diag.interface_health_findings(ifaces, counters)["findings"] == []


@pytest.mark.unit
def test_interface_missing_fields_do_not_crash():
    # A disabled+down port is expected (not flagged); missing counters/flap tolerated.
    ifaces = [{"interface": "Eth1", "is_up": False, "is_enabled": False}, {}]
    result = diag.interface_health_findings(ifaces, [])
    assert result["findings"] == []
    assert result["interfacesAnalyzed"] == 2


@pytest.mark.unit
def test_interface_findings_are_worst_first():
    ifaces = [
        {"interface": "Eth1", "is_up": True, "is_enabled": True, "last_flapped": 10.0},
        {"interface": "Eth2", "is_up": False, "is_enabled": True},
    ]
    findings = diag.interface_health_findings(ifaces, [])["findings"]
    assert findings[0]["severity"] == "critical"  # the down port ranks first


# ── bgp_neighbor_findings ─────────────────────────────────────────────────


@pytest.mark.unit
def test_bgp_down_session_is_critical():
    peers = [
        {
            "vrf": "global",
            "neighbor": "10.0.0.2",
            "remote_as": 65001,
            "is_up": False,
            "is_enabled": True,
        }
    ]
    result = diag.bgp_neighbor_findings(peers)
    assert result["sessionsDown"] == 1
    f = result["findings"][0]
    assert f["severity"] == "critical"
    assert f["signal"] == "BGP session down"
    assert "ACL" in f["action"] or "MD5" in f["action"]


@pytest.mark.unit
def test_bgp_admin_shut_is_info_not_down():
    peers = [
        {
            "vrf": "global",
            "neighbor": "10.0.0.2",
            "remote_as": 65001,
            "is_up": False,
            "is_enabled": False,
        }
    ]
    result = diag.bgp_neighbor_findings(peers)
    assert result["sessionsDown"] == 0
    assert result["findings"][0]["severity"] == "info"
    assert result["findings"][0]["signal"] == "BGP session shut"


@pytest.mark.unit
def test_bgp_recently_reset_is_warning_and_cites_uptime():
    peers = [
        {
            "vrf": "global",
            "neighbor": "10.0.0.2",
            "remote_as": 65001,
            "is_up": True,
            "is_enabled": True,
            "uptime": 42,
            "received_prefixes": 5,
        }
    ]
    f = diag.bgp_neighbor_findings(peers)["findings"][0]
    assert f["signal"] == "BGP session recently reset"
    assert "42s" in f["detail"]


@pytest.mark.unit
def test_bgp_up_but_no_prefixes_is_info():
    peers = [
        {
            "vrf": "global",
            "neighbor": "10.0.0.2",
            "remote_as": 65001,
            "is_up": True,
            "is_enabled": True,
            "uptime": 99999,
            "received_prefixes": 0,
        }
    ]
    f = diag.bgp_neighbor_findings(peers)["findings"][0]
    assert f["signal"] == "BGP no prefixes received"
    assert f["severity"] == "info"


@pytest.mark.unit
def test_bgp_healthy_established_session_is_clean():
    peers = [
        {
            "vrf": "global",
            "neighbor": "10.0.0.2",
            "remote_as": 65001,
            "is_up": True,
            "is_enabled": True,
            "uptime": 99999,
            "received_prefixes": 10,
        }
    ]
    assert diag.bgp_neighbor_findings(peers)["findings"] == []


@pytest.mark.unit
def test_bgp_missing_fields_do_not_crash():
    result = diag.bgp_neighbor_findings([{}])
    assert result["neighborsAnalyzed"] == 1
    # empty peer: is_up/is_enabled both falsey → treated as admin-shut (info)
    assert result["findings"][0]["severity"] == "info"


# ── MCP tools over a mocked NAPALM driver ─────────────────────────────────


class _FakeDriver:
    """NAPALM driver double: one down port with errors, one flapping BGP peer."""

    def __init__(self, hostname=None, username=None, password=None, optional_args=None):
        pass

    def open(self):
        return None

    def close(self):
        return None

    def get_interfaces(self):
        return {
            "Ethernet1": {
                "is_up": True,
                "is_enabled": True,
                "speed": 10000,
                "description": "uplink",
                "mac_address": "00:11:22:33:44:55",
                "last_flapped": -1.0,
            },
            "Ethernet2": {
                "is_up": False,
                "is_enabled": True,
                "speed": 1000,
                "description": "down link",
                "mac_address": "",
                "last_flapped": 15.0,
            },
        }

    def get_interfaces_counters(self):
        return {
            "Ethernet1": {"rx_errors": 0, "tx_errors": 0, "rx_discards": 0, "tx_discards": 0},
            "Ethernet2": {"rx_errors": 500, "tx_errors": 0, "rx_discards": 0, "tx_discards": 0},
        }

    def get_bgp_neighbors(self):
        return {
            "global": {
                "peers": {
                    "10.0.0.2": {
                        "remote_as": 65001,
                        "is_up": False,
                        "is_enabled": True,
                        "uptime": 0,
                        "address_family": {
                            "ipv4": {"received_prefixes": 0, "accepted_prefixes": 0}
                        },
                    }
                }
            }
        }


def _target_config():
    from network_aiops.config import TargetConfig

    return TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


@pytest.mark.unit
def test_interface_health_rca_tool_collects_and_is_governed(monkeypatch):
    import network_aiops.connection as conn_mod
    from mcp_server.tools import diagnostics as diag_tools

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: _FakeDriver)
    monkeypatch.setattr(diag_tools, "_target", lambda name=None: _target_config())

    assert diag_tools.interface_health_rca._is_governed_tool is True

    result = diag_tools.interface_health_rca(target="core-sw1")
    assert "error" not in result
    assert result["interfacesAnalyzed"] == 2
    # Ethernet2 is admin-up/oper-down → critical, ranked first.
    assert result["findings"][0]["severity"] == "critical"
    assert result["findings"][0]["entity"] == "Ethernet2"


@pytest.mark.unit
def test_bgp_neighbor_rca_tool_collects_and_is_governed(monkeypatch):
    import network_aiops.connection as conn_mod
    from mcp_server.tools import diagnostics as diag_tools

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: _FakeDriver)
    monkeypatch.setattr(diag_tools, "_target", lambda name=None: _target_config())

    assert diag_tools.bgp_neighbor_rca._is_governed_tool is True

    result = diag_tools.bgp_neighbor_rca(target="core-sw1")
    assert "error" not in result
    assert result["neighborsAnalyzed"] == 1
    assert result["sessionsDown"] == 1
    assert result["findings"][0]["signal"] == "BGP session down"


@pytest.mark.unit
def test_rank_assigns_explicit_worst_first_rank():
    """Findings state their priority explicitly, not implicitly by list order.

    A consumer — notably a smaller local model summarising the result — must not
    have to infer urgency from a finding's position in the list.
    """
    from network_aiops.ops import diagnostics as _diag

    ranked = _diag._rank([{"severity": "info"}, {"severity": "critical"}, {"severity": "warning"}])
    assert [f["severity"] for f in ranked] == ["critical", "warning", "info"]
    assert [f["rank"] for f in ranked] == [1, 2, 3]
