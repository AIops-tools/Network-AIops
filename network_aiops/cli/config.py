"""``network-aiops config ...`` sub-commands (backup / diff / merge / replace / confirm / rollback).

Merge and replace commit under a device-side revert timer (``--revert-in``,
default 300s): the device rolls the change back on its own unless
``network-aiops config confirm`` follows. That is the only guard that survives
the change severing your own management path, so the workflow is
merge/replace → check reachability → confirm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from mcp_server.tools import config_ops as gov
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
from network_aiops.ops.config_ops import DEFAULT_REVERT_IN

config_app = typer.Typer(help="Device configuration operations.", no_args_is_help=True)
console = Console()

RevertInOption = Annotated[
    int,
    typer.Option(
        "--revert-in",
        help=(
            "Device-side revert timer in seconds; the device undoes the change "
            "unless 'config confirm' follows. 0 disables the timer."
        ),
    ),
]


def _resolve(target: str | None):
    return get_manager().target(target)


def _require_ok(result: dict) -> dict:
    """Surface a governed tool's sanitised ``{"error": ...}`` as a CLI failure.

    The governed twins are wrapped in ``@tool_errors``, which turns a refusal
    (e.g. ``UnreversibleCommit``) into an error dict rather than an exception.
    Without this the CLI would print a "success" banner over a refusal.
    """
    if isinstance(result, dict) and result.get("error"):
        console.print(f"[red]Error: {result['error']}[/]")
        raise typer.Exit(1)
    return result


def _print_preview(result: dict) -> None:
    """Echo a dry-run: the diff plus whether the real commit would have a net.

    The preview runs the same refusal as the write, so reaching here at all
    means the commit would not be refused.
    """
    console.print(result["diff"] or "[dim](no changes)[/]")
    commit = result.get("commit") or {}
    if commit.get("warning"):
        console.print(f"[bold red]{commit['warning']}[/]")
    elif commit.get("wouldArmTimer"):
        console.print(
            f"[yellow]Would commit with a {commit['revertInSeconds']}s revert timer; "
            f"'config confirm' makes it permanent.[/]"
        )


def _print_commit(result: dict) -> None:
    """Echo the diff plus how the commit was actually made (timer or not)."""
    console.print(result["diff"] or "[dim](no changes)[/]")
    commit = result.get("commit") or {}
    if commit.get("warning"):
        console.print(f"[bold red]{commit['warning']}[/]")
    if commit.get("next"):
        console.print(f"[yellow]{commit['next']}[/]")


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
    revert_in: RevertInOption = DEFAULT_REVERT_IN,
) -> None:
    """Merge a config snippet and commit under a revert timer (double confirm)."""
    text = read_config_text(config_file)
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="config_merge", detail=f"merge into {tgt.name}")
        # Through the GOVERNED twin, not the ops layer: the preview then runs the
        # same guard AND lands the same audit row as any other governed call.
        _print_preview(_require_ok(
            gov.config_merge(config_text=text, target=target, revert_in=revert_in,
                             dry_run=True)
        ))
        return
    double_confirm("merge config into", tgt.name)
    result = _require_ok(gov.config_merge(config_text=text, target=target, revert_in=revert_in))
    console.print(f"[green]Committed merge to {result['name']}[/]")
    _print_commit(result)


@config_app.command("replace")
@cli_errors
def config_replace_cmd(
    config_file: Path,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
    revert_in: RevertInOption = DEFAULT_REVERT_IN,
) -> None:
    """Replace the full config under a revert timer (HIGH RISK — double confirm)."""
    text = read_config_text(config_file)
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="config_replace", detail=f"replace config of {tgt.name}")
        _print_preview(_require_ok(
            gov.config_replace(config_text=text, target=target, revert_in=revert_in,
                               dry_run=True)
        ))
        return
    double_confirm("REPLACE config of", tgt.name)
    result = _require_ok(gov.config_replace(config_text=text, target=target, revert_in=revert_in))
    console.print(f"[green]Committed replace to {result['name']}[/]")
    _print_commit(result)


@config_app.command("confirm")
@cli_errors
def config_confirm_cmd(
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Confirm a pending commit-confirm change, cancelling its revert timer."""
    tgt = _resolve(target)
    if dry_run:
        dry_run_print(operation="confirm_commit", detail=f"confirm pending commit on {tgt.name}")
        return
    result = _require_ok(gov.confirm_commit(target=target))
    if result.get("confirmed"):
        console.print(f"[green]Confirmed the pending commit on {tgt.name} — now permanent.[/]")
    else:
        console.print(f"[yellow]{result.get('note', 'Nothing to confirm.')}[/]")


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
    gov.config_rollback(target=target)
    console.print(f"[green]Rolled back the last commit on {tgt.name}[/]")
