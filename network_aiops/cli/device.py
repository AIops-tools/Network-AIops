"""``network-aiops device ...`` sub-commands (read-only facts)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from network_aiops.cli._common import TargetOption, cli_errors, get_manager
from network_aiops.ops import facts

device_app = typer.Typer(help="Device facts and read-only state.", no_args_is_help=True)
console = Console()


def _resolve(target: str | None):
    mgr = get_manager()
    return mgr.target(target)


@device_app.command("facts")
@cli_errors
def device_facts_cmd(target: TargetOption = None) -> None:
    """Show core device facts (hostname, vendor, model, OS, serial, uptime)."""
    result = facts.device_facts(_resolve(target))
    for k in ("name", "hostname", "vendor", "model", "os_version",
              "serial_number", "uptime_seconds", "interface_count"):
        console.print(f"  [cyan]{k}:[/] {result.get(k)}")


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
            r["interface"], str(r["is_up"]), str(r["is_enabled"]),
            str(r["speed"]), r["description"],
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
            r["vrf"], r["neighbor"], str(r["remote_as"]),
            str(r["is_up"]), str(r["received_prefixes"]),
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
        table.add_row(r["local_port"], r["remote_host"], r["remote_port"])
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
        table.add_row(r["interface"], r["ip"], r["mac"], str(r["age"]))
    console.print(table)
