"""``network-aiops netbox ...`` sub-commands (optional source-of-truth)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from network_aiops.cli._common import cli_errors, get_manager
from network_aiops.ops import netbox_ops

netbox_app = typer.Typer(help="NetBox source-of-truth lookups (optional).", no_args_is_help=True)
console = Console()


@netbox_app.command("list")
@cli_errors
def netbox_list_cmd(
    name: str = typer.Option(None, "--name", help="Filter by name (contains)"),
    limit: int = typer.Option(50, "--limit", help="Max devices to return"),
) -> None:
    """List NetBox devices (name, role, site, status, primary IP)."""
    api = get_manager().netbox()
    rows = netbox_ops.netbox_list_devices(api, limit=limit, name=name)
    table = Table(title="NetBox Devices")
    for col in ("name", "role", "site", "status", "primary_ip"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["name"], r["role"], r["site"], r["status"], r["primary_ip"])
    console.print(table)


@netbox_app.command("get")
@cli_errors
def netbox_get_cmd(name: str) -> None:
    """Show a single NetBox device by exact name."""
    api = get_manager().netbox()
    for k, v in netbox_ops.netbox_get_device(api, name).items():
        console.print(f"  [cyan]{k}:[/] {v}")
