"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from network_aiops.cli.config import config_app
from network_aiops.cli.device import device_app
from network_aiops.cli.doctor import doctor_cmd
from network_aiops.cli.init import init_cmd
from network_aiops.cli.netbox import netbox_app
from network_aiops.cli.secret import secret_app

app = typer.Typer(
    name="network-aiops",
    help="Governed multi-vendor network device operations for AI agents (NAPALM).",
    no_args_is_help=True,
)

app.add_typer(device_app, name="device")
app.add_typer(config_app, name="config")
app.add_typer(netbox_app, name="netbox")
app.add_typer(secret_app, name="secret")
app.command("init")(init_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        network-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: network-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force network-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
