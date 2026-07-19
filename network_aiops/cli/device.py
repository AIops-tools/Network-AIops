"""``network-aiops device ...`` sub-commands (read-only facts)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from network_aiops.cli._common import TargetOption, cli_errors, get_manager
from network_aiops.ops import environment as env_ops
from network_aiops.ops import facts
from network_aiops.ops import health as health_ops
from network_aiops.ops import inventory as inv_ops

device_app = typer.Typer(help="Device facts and read-only state.", no_args_is_help=True)
console = Console()


def _resolve(target: str | None):
    mgr = get_manager()
    return mgr.target(target)


def _cell(value: object) -> str:
    """Render one cell, keeping "absent" visually distinct from a literal value.

    An optional field the device never returned is ``None`` at the ops layer.
    Stringifying it would print the word ``None``, which reads like data; an
    em dash reads like "not reported", which is what it is.
    """
    return "—" if value is None else str(value)


def _simple_table(title: str, columns: tuple[str, ...], rows: list[dict]) -> None:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for r in rows:
        table.add_row(*[_cell(r.get(c)) for c in columns])
    console.print(table)


@device_app.command("facts")
@cli_errors
def device_facts_cmd(target: TargetOption = None) -> None:
    """Show core device facts (hostname, vendor, model, OS, serial, uptime)."""
    result = facts.device_facts(_resolve(target))
    for k in ("name", "hostname", "vendor", "model", "os_version",
              "serial_number", "uptime_seconds", "interface_count"):
        console.print(f"  [cyan]{k}:[/] {_cell(result.get(k))}")


@device_app.command("interfaces")
@cli_errors
def device_interfaces_cmd(target: TargetOption = None) -> None:
    """List interfaces (up/down, enabled, speed, description)."""
    rows = facts.get_interfaces(_resolve(target))
    table = Table(title="Interfaces")
    for col in ("interface", "is_up", "is_enabled", "speed", "description"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            _cell(r["interface"]), str(r["is_up"]), str(r["is_enabled"]),
            _cell(r["speed"]), _cell(r["description"]),
        )
    console.print(table)


@device_app.command("bgp")
@cli_errors
def device_bgp_cmd(target: TargetOption = None) -> None:
    """Show BGP neighbors (vrf, neighbor, remote AS, up, prefixes)."""
    rows = facts.get_bgp_neighbors(_resolve(target))
    table = Table(title="BGP Neighbors")
    for col in ("vrf", "neighbor", "remote_as", "is_up", "received_prefixes"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            _cell(r["vrf"]), _cell(r["neighbor"]), _cell(r["remote_as"]),
            str(r["is_up"]), _cell(r["received_prefixes"]),
        )
    console.print(table)


@device_app.command("lldp")
@cli_errors
def device_lldp_cmd(target: TargetOption = None) -> None:
    """Show LLDP neighbors (local port, remote host, remote port)."""
    rows = facts.get_lldp_neighbors(_resolve(target))
    table = Table(title="LLDP Neighbors")
    for col in ("local_port", "remote_host", "remote_port"):
        table.add_column(col)
    for r in rows:
        table.add_row(_cell(r["local_port"]), _cell(r["remote_host"]), _cell(r["remote_port"]))
    console.print(table)


@device_app.command("arp")
@cli_errors
def device_arp_cmd(target: TargetOption = None) -> None:
    """Show the ARP table (interface, IP, MAC, age)."""
    rows = facts.get_arp_table(_resolve(target))
    table = Table(title="ARP Table")
    for col in ("interface", "ip", "mac", "age"):
        table.add_column(col)
    for r in rows:
        table.add_row(_cell(r["interface"]), _cell(r["ip"]), _cell(r["mac"]), _cell(r["age"]))
    console.print(table)


@device_app.command("counters")
@cli_errors
def device_counters_cmd(target: TargetOption = None) -> None:
    """Show interface traffic + error counters."""
    rows = inv_ops.get_interfaces_counters(_resolve(target))
    _simple_table(
        "Interface Counters",
        ("interface", "rx_octets", "tx_octets", "rx_errors", "tx_errors"),
        rows,
    )


@device_app.command("mac")
@cli_errors
def device_mac_cmd(target: TargetOption = None) -> None:
    """Show the MAC address table (MAC, interface, VLAN, static/active)."""
    rows = inv_ops.get_mac_address_table(_resolve(target))
    _simple_table("MAC Address Table", ("mac", "interface", "vlan", "static", "active"), rows)


@device_app.command("vlans")
@cli_errors
def device_vlans_cmd(target: TargetOption = None) -> None:
    """Show VLANs (id, name, interface count)."""
    rows = inv_ops.get_vlans(_resolve(target))
    table = Table(title="VLANs")
    for col in ("vlan_id", "name", "interfaces"):
        table.add_column(col)
    for r in rows:
        table.add_row(_cell(r["vlan_id"]), _cell(r["name"]), str(len(r["interfaces"])))
    console.print(table)


@device_app.command("route")
@cli_errors
def device_route_cmd(
    destination: str,
    target: TargetOption = None,
    protocol: str = typer.Option("", "--protocol", help="Filter by protocol (bgp, ospf, ...)"),
) -> None:
    """Look up the routing table for a destination prefix."""
    rows = inv_ops.get_route_to(_resolve(target), destination, protocol)
    _simple_table(
        f"Route to {destination}",
        ("prefix", "protocol", "next_hop", "outgoing_interface", "current_active"),
        rows,
    )


@device_app.command("environment")
@cli_errors
def device_environment_cmd(target: TargetOption = None) -> None:
    """Show hardware environment (fans, temperature, power, CPU, memory)."""
    env = env_ops.get_environment(_resolve(target))
    console.print(f"[bold]Environment for {env['name']}[/]")
    console.print(f"  fans: {env['fans']}")
    console.print(f"  temperature: {env['temperature']}")
    console.print(f"  power: {env['power']}")
    console.print(f"  cpu: {env['cpu']}")
    console.print(f"  memory: {env['memory']}")


@device_app.command("health")
@cli_errors
def device_health_cmd(target: TargetOption = None) -> None:
    """Show an aggregated health summary (facts + interfaces + environment)."""
    h = health_ops.device_health(_resolve(target))
    status = "[green]HEALTHY[/]" if h["healthy"] else "[red]ISSUES[/]"
    console.print(
        f"[bold]{h['name']} ({_cell(h['hostname'])}, {_cell(h['model'])})[/] — {status}"
    )
    console.print(f"  interfaces: {h['interfaces']}")
    if h["environment"]:
        console.print(f"  environment: {h['environment']}")
    for issue in h["issues"]:
        console.print(f"  [yellow]! {issue}[/]")
    for note in h["notes"]:
        console.print(f"  [dim]note: {note}[/]")
