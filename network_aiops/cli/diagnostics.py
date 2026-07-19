"""``network-aiops diagnose ...`` sub-commands — read-only RCA over a device."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from network_aiops.cli._common import TargetOption, cli_errors, get_manager
from network_aiops.ops import diagnostics as diag
from network_aiops.ops import facts
from network_aiops.ops import inventory as inv_ops

diagnose_app = typer.Typer(
    help="Read-only diagnostics / RCA over a device.", no_args_is_help=True
)
console = Console()

_SEVERITY_STYLE = {"critical": "red", "warning": "yellow", "info": "cyan"}


def _resolve(target: str | None):
    return get_manager().target(target)


def _print_findings(findings: list[dict]) -> None:
    """Render worst-first findings as a table, or a green all-clear line."""
    if not findings:
        console.print("[green]No findings — all measured values under threshold.[/]")
        return
    table = Table(title="Findings (worst first)")
    for col in ("severity", "entity", "signal", "detail", "action"):
        table.add_column(col, overflow="fold")
    for f in findings:
        style = _SEVERITY_STYLE.get(f["severity"], "white")
        table.add_row(
            f"[{style}]{f['severity']}[/]", f.get("entity", ""),
            f["signal"], f["detail"], f["action"],
        )
    console.print(table)


@diagnose_app.command("interface-health")
@cli_errors
def diagnose_interface_health(target: TargetOption = None) -> None:
    """Flag admin-up/oper-down interfaces, error/discard counters, recent flaps."""
    dev = _resolve(target)
    result = diag.interface_health_findings(
        facts.get_interfaces(dev), inv_ops.get_interfaces_counters(dev)
    )
    console.print(f"[bold]Analyzed {result['interfacesAnalyzed']} interface(s).[/]")
    _print_findings(result["findings"])


@diagnose_app.command("bgp")
@cli_errors
def diagnose_bgp(target: TargetOption = None) -> None:
    """Flag BGP neighbors not up / recently reset / learning no prefixes."""
    dev = _resolve(target)
    result = diag.bgp_neighbor_findings(facts.get_bgp_neighbors(dev))
    console.print(
        f"[bold]Analyzed {result['neighborsAnalyzed']} neighbor(s); "
        f"{result['sessionsDown']} down.[/]"
    )
    _print_findings(result["findings"])
