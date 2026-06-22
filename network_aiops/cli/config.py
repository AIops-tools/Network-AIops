"""``network-aiops config ...`` sub-commands (backup / diff / merge / replace / rollback)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from network_aiops.cli._common import (
    DryRunOption,
    OutputOption,
    TargetOption,
    cli_errors,
    double_confirm,
    dry_run_print,
    get_manager,
    read_config_text,
)
from network_aiops.ops import config_ops

config_app = typer.Typer(help="Device configuration operations.", no_args_is_help=True)
console = Console()


def _resolve(target: str | None):
    return get_manager().target(target)


@config_app.command("backup")
@cli_errors
def config_backup_cmd(target: TargetOption = None, output: OutputOption = None) -> None:
    """Fetch the running config (optionally save it to a file with -o)."""
    result = config_ops.config_backup(_resolve(target))
    if output is not None:
        Path(output).write_text(result["config"])
        console.print(f"[green]Saved running config of {result['name']} -> {output}[/]")
    else:
        console.print(result["config"])


@config_app.command("diff")
@cli_errors
def config_diff_cmd(
    config_file: Path,
    target: TargetOption = None,
    replace: bool = typer.Option(False, "--replace", help="Diff as a full replace"),
) -> None:
    """Dry-run: show the diff a config file would produce (nothing is committed)."""
    text = read_config_text(config_file)
    result = config_ops.config_diff(_resolve(target), text, replace=replace)
    console.print(f"[bold]Diff ({result['mode']}, not committed):[/]")
    console.print(result["diff"] or "[dim](no changes)[/]")


@config_app.command("merge")
@cli_errors
def config_merge_cmd(
    config_file: Path,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Merge a config snippet and commit (double confirm; --dry-run shows the diff)."""
    text = read_config_text(config_file)
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="config_merge", detail=f"merge into {tgt.name}")
        result = config_ops.config_diff(tgt, text, replace=False)
        console.print(result["diff"] or "[dim](no changes)[/]")
        return
    double_confirm("merge config into", tgt.name)
    result = config_ops.config_merge(tgt, text)
    console.print(f"[green]Committed merge to {result['name']}[/]")
    console.print(result["diff"] or "[dim](no changes)[/]")


@config_app.command("replace")
@cli_errors
def config_replace_cmd(
    config_file: Path,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Replace the full config and commit (HIGH RISK — double confirm; --dry-run shows diff)."""
    text = read_config_text(config_file)
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="config_replace", detail=f"replace config of {tgt.name}")
        result = config_ops.config_diff(tgt, text, replace=True)
        console.print(result["diff"] or "[dim](no changes)[/]")
        return
    double_confirm("REPLACE config of", tgt.name)
    result = config_ops.config_replace(tgt, text)
    console.print(f"[green]Committed replace to {result['name']}[/]")
    console.print(result["diff"] or "[dim](no changes)[/]")


@config_app.command("rollback")
@cli_errors
def config_rollback_cmd(
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Revert the last committed change (double confirm; device support varies)."""
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="config_rollback", detail=f"rollback {tgt.name}")
        return
    double_confirm("rollback last commit on", tgt.name)
    config_ops.config_rollback(tgt)
    console.print(f"[green]Rolled back the last commit on {tgt.name}[/]")
