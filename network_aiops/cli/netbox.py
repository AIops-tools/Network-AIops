"""``network-aiops netbox ...`` sub-commands (optional source-of-truth)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from network_aiops.cli._common import cli_errors, get_manager
from network_aiops.cli.device import _cell
from network_aiops.ops import netbox_ops

netbox_app = typer.Typer(help="NetBox source-of-truth lookups (optional).", no_args_is_help=True)
console = Console()


def _print_truncation(result: dict) -> None:
    """Say out loud when the result was capped, instead of leaving it implied."""
    if result.get("truncated"):
        console.print(
            f"  [yellow]{result['returned']} of more than {result['limit']} shown — "
            f"truncated, re-run with a higher --limit.[/]"
        )


@netbox_app.command("list")
@cli_errors
def netbox_list_cmd(
    name: str = typer.Option(None, "--name", help="Filter by name (contains)"),
    limit: int = typer.Option(50, "--limit", help="Max devices to return"),
) -> None:
    """List NetBox devices (name, role, site, status, primary IP)."""
    api = get_manager().netbox()
    result = netbox_ops.netbox_list_devices(api, limit=limit, name=name)
    table = Table(title="NetBox Devices")
    for col in ("name", "role", "site", "status", "primary_ip"):
        table.add_column(col)
    for r in result["devices"]:
        table.add_row(
            _cell(r["name"]), _cell(r["role"]), _cell(r["site"]),
            _cell(r["status"]), _cell(r["primary_ip"]),
        )
    console.print(table)
    _print_truncation(result)


@netbox_app.command("get")
@cli_errors
def netbox_get_cmd(name: str) -> None:
    """Show a single NetBox device by exact name."""
    api = get_manager().netbox()
    for k, v in netbox_ops.netbox_get_device(api, name).items():
        console.print(f"  [cyan]{k}:[/] {_cell(v)}")


@netbox_app.command("interfaces")
@cli_errors
def netbox_interfaces_cmd(
    device: str,
    limit: int = typer.Option(100, "--limit", help="Max interfaces to return"),
) -> None:
    """List a NetBox device's interfaces (from source-of-truth)."""
    api = get_manager().netbox()
    result = netbox_ops.netbox_device_interfaces(api, device, limit=limit)
    table = Table(title=f"NetBox interfaces — {device}")
    for col in ("name", "type", "enabled", "description"):
        table.add_column(col)
    for r in result["interfaces"]:
        table.add_row(
            _cell(r["name"]), _cell(r["type"]), str(r["enabled"]), _cell(r["description"])
        )
    console.print(table)
    _print_truncation(result)
