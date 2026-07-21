"""Shared fixtures for the network-aiops test suite (no live device).

NAPALM drivers and pynetbox are always mocked; these fixtures only shape the
governance environment the tools run under.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_approver(monkeypatch):
    """Record a synthetic approver annotation globally.

    The harness authorizes nothing, so this gates nothing; it only ensures the
    optional ``approved_by`` audit field is populated for tests that do not set
    their own. The governance-persistence tests clear it to show the annotation
    is genuinely optional."""
    monkeypatch.setenv("NETWORK_AUDIT_APPROVED_BY", "pytest")


# ── Shared test doubles ─────────────────────────────────────────────────────


class FakeDriver:
    """A rich NAPALM driver double covering every getter + config call the ops
    layer, MCP tools, and CLI commands touch. State-changing calls flip flags so
    tests can assert commit/rollback plumbing without a live device."""

    def __init__(self, hostname=None, username=None, password=None, optional_args=None):
        self.hostname = hostname
        self.optional_args = optional_args
        self.opened = False
        self.closed = False
        self.committed = False
        self.discarded = False
        self.rolled_back = False
        self.revert_in = None
        self.pending_commit = False
        self.confirmed = False
        self._candidate = None

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def get_facts(self):
        return {
            "hostname": "core-sw1", "fqdn": "core-sw1.lab", "vendor": "Arista",
            "model": "DCS-7050", "os_version": "4.30.1F", "serial_number": "ABC123",
            "uptime": 123456, "interface_list": ["Ethernet1", "Ethernet2"],
        }

    def get_interfaces(self):
        return {
            "Ethernet1": {"is_up": True, "is_enabled": True, "speed": 10000,
                          "description": "uplink", "mac_address": "00:11:22:33:44:55"},
            "Ethernet2": {"is_up": False, "is_enabled": True, "speed": 10000,
                          "description": "down-link", "mac_address": "00:11:22:33:44:66"},
        }

    def get_interfaces_ip(self):
        return {
            "Ethernet1": {
                "ipv4": {"10.0.0.1": {"prefix_length": 24}},
                "ipv6": {"2001:db8::1": {"prefix_length": 64}},
            }
        }

    def get_bgp_neighbors(self):
        return {"global": {"peers": {"10.0.0.2": {
            "remote_as": 65001, "is_up": True, "is_enabled": True,
            "address_family": {"ipv4": {"received_prefixes": 10, "accepted_prefixes": 10}},
        }}}}

    def get_lldp_neighbors(self):
        return {"Ethernet1": [{"hostname": "core-sw2", "port": "Ethernet1"}]}

    def get_arp_table(self):
        return [{"interface": "Ethernet1", "ip": "10.0.0.2",
                 "mac": "00:aa:bb:cc:dd:ee", "age": 12.0}]

    def get_bgp_neighbors_detail(self):
        return {"global": {"10.0.0.2": [{
            "up": True, "local_as": 65000, "remote_as": 65001,
            "remote_router_id": "10.0.0.2", "connection_state": "Established",
            "received_prefix_count": 10, "accepted_prefix_count": 10,
            "advertised_prefix_count": 5,
        }]}}

    def get_lldp_neighbors_detail(self):
        return {"Ethernet1": [{
            "remote_chassis_id": "aabb.ccdd.eeff", "remote_system_name": "core-sw2",
            "remote_port": "Ethernet1", "remote_port_description": "to core-sw1",
            "remote_system_description": "Arista EOS",
            "remote_system_capab": ["bridge", "router"],
            "remote_system_enable_capab": ["bridge"],
        }]}

    def get_interfaces_counters(self):
        return {"Ethernet1": {"tx_octets": 1000, "rx_octets": 2000,
                              "tx_unicast_packets": 10, "rx_unicast_packets": 20,
                              "tx_errors": 0, "rx_errors": 1,
                              "tx_discards": 0, "rx_discards": 0}}

    def get_mac_address_table(self):
        return [{"mac": "00:aa:bb:cc:dd:ee", "interface": "Ethernet1", "vlan": 10,
                 "static": False, "active": True, "moves": 0, "last_move": 0.0}]

    def get_vlans(self):
        return {"10": {"name": "users", "interfaces": ["Ethernet1", "Ethernet2"]}}

    def get_route_to(self, destination, protocol=""):
        return {destination: [{"protocol": "bgp", "current_active": True,
                               "next_hop": "10.0.0.2", "outgoing_interface": "Ethernet1",
                               "preference": 200, "selected_next_hop": True}]}

    def get_environment(self):
        return {
            "fans": {"Fan1": {"status": True}},
            "temperature": {"sensor1": {"temperature": 40.0, "is_alert": False,
                                        "is_critical": False}},
            "power": {"PSU1": {"status": True, "capacity": 600.0, "output": 100.0}},
            "cpu": {"0": {"%usage": 12.5}},
            "memory": {"available_ram": 1000000, "used_ram": 400000},
        }

    def get_optics(self):
        return {"Ethernet1": {"physical_channels": {"channel": [{
            "index": 0, "state": {
                "input_power": {"instant": -3.0}, "output_power": {"instant": -2.0},
                "laser_bias_current": {"instant": 30.0}}}]}}}

    def get_ntp_servers(self):
        return {"10.0.0.99": {}}

    def get_ntp_stats(self):
        return [{"remote": "10.0.0.99", "synchronized": True, "stratum": 2,
                 "type": "u", "reachability": 377, "delay": 1.0,
                 "offset": 0.1, "jitter": 0.05}]

    def get_users(self):
        return {"admin": {"level": 15, "password": "$1$secrethash",
                          "sshkeys": ["ssh-rsa AAA"]}}

    def get_snmp_information(self):
        return {"chassis_id": "ABC123", "community": {"public": {"mode": "ro"}},
                "contact": "noc@lab", "location": "rack1"}

    def get_network_instances(self):
        return {"MGMT": {"name": "MGMT", "type": "L3VRF",
                         "state": {"route_distinguisher": "65000:1"},
                         "interfaces": {"interface": {"Ethernet1": {}}}}}

    def get_config(self, retrieve="running"):
        return {"running": "hostname core-sw1\n", "startup": "", "candidate": ""}

    def load_merge_candidate(self, config=None):
        self._candidate = config

    def load_replace_candidate(self, config=None):
        self._candidate = config

    def compare_config(self):
        return "+ ntp server 10.0.0.99"

    def discard_config(self):
        self.discarded = True
        self._candidate = None

    def commit_config(self, message="", revert_in=None):
        """Commit, optionally arming a device-side revert timer (NAPALM >= 3.0)."""
        self.committed = True
        self.revert_in = revert_in
        if revert_in is not None:
            self.pending_commit = True

    def has_pending_commit(self):
        return self.pending_commit

    def confirm_commit(self):
        self.confirmed = True
        self.pending_commit = False

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def fake_driver_cls(monkeypatch):
    """Route ``connection._driver_for`` to the shared FakeDriver class."""
    import network_aiops.connection as conn_mod

    monkeypatch.setattr(conn_mod, "_driver_for", lambda target: FakeDriver)
    return FakeDriver


@pytest.fixture
def eos_target():
    from network_aiops.config import TargetConfig

    return TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    """Isolate the governance state (audit/undo) into a throwaway home so
    governed-tool tests never touch the real ~/.network-aiops."""
    import network_aiops.governance.audit as audit_mod
    import network_aiops.governance.policy as policy_mod
    import network_aiops.governance.undo as undo_mod

    monkeypatch.setenv("NETWORK_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
