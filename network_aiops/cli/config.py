"""``network-aiops config ...`` sub-commands (backup / diff / merge / replace / confirm / rollback).

Merge and replace commit under a device-side revert timer (``--revert-in``,
default 300s): the device rolls the change back on its own unless
``network-aiops config confirm`` follows. That is the only guard that survives
the change severing your own management path, so the workflow is
merge/replace → check reachability → confirm.

Config text printed to STDOUT has credential values masked; ``backup -o <path>``
writes the file verbatim. The split is deliberate: stdout is what an agent
driving this CLI reads, a path is what an operator chose.
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
    dry_run_preview,
    dry_run_print,
    get_manager,
    read_config_text,
)
from network_aiops.ops import config_ops
from network_aiops.ops.config_ops import DEFAULT_REVERT_IN

config_app = typer.Typer(help="Device configuration operations.", no_args_is_help=True)
console = Console()

IncludeSecretsOption = Annotated[
    bool,
    typer.Option(
        "--include-secrets",
        help=(
            "Print credential values verbatim instead of masking them. Ignored "
            "with -o, which always writes the raw config to the file."
        ),
    ),
]

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


def _print_redaction(result: dict) -> None:
    """Say out loud that the text above was altered, and how to get it verbatim.

    The JSON carries a ``redaction`` block, but a human scrolling a 3000-line
    config will not scroll back for it — and neither will a model summarising
    the terminal. Redaction that the reader cannot notice is the silent
    transformation this line treats as a defect, so it gets its own last line.
    """
    redaction = result.get("redaction") or {}
    if not redaction.get("applied"):
        return
    count = redaction.get("linesRedacted") or 0
    if count:
        console.print(
            f"[yellow]… {count} line(s) had credential values masked as "
            f"'<redacted>'. Use -o <path> to save the raw config to a file, or "
            f"--include-secrets to print it here.[/]"
        )
    else:
        console.print(
            "[dim]… no credential lines matched. Redaction is pattern-based and "
            "cannot see multi-line key blocks, so this is not proof of none.[/]"
        )


def _preview_params(result: dict) -> dict:
    """Banner params taken from the GOVERNED preview, not guessed by the CLI.

    ``wouldArmTimer`` is the device-side answer (the driver's ``commit_config``
    signature was actually probed), so this reports what the commit would do
    rather than what the flags asked for — the two differ on drivers that
    cannot arm a revert timer.
    """
    commit = result.get("commit") or {}
    return {
        "mode": result.get("mode"),
        "safetyNet": commit.get("safetyNet"),
        "revertInSeconds": commit.get("revertInSeconds"),
    }


def _print_preview(result: dict) -> None:
    """Echo a dry-run: the diff plus whether the real commit would have a net.

    The preview runs the same refusal as the write, so reaching here at all
    means the commit would not be refused.
    """
    console.print(result["diff"] or "[dim](no changes)[/]")
    _print_redaction(result)
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
    _print_redaction(result)
    commit = result.get("commit") or {}
    if commit.get("warning"):
        console.print(f"[bold red]{commit['warning']}[/]")
    if commit.get("next"):
        console.print(f"[yellow]{commit['next']}[/]")


@config_app.command("backup")
@cli_errors
def config_backup_cmd(
    target: TargetOption = None,
    output: OutputOption = None,
    include_secrets: IncludeSecretsOption = False,
) -> None:
    """Fetch the running config (raw to a file with -o; credentials masked on stdout).

    The two sinks are treated differently ON PURPOSE. ``-o <path>`` writes the
    verbatim config, because a backup with its keys stripped out is not a backup
    — and the operator named that file, so they chose where it lands. stdout
    masks credentials by default, because stdout is where an agent driving this
    CLI reads from, and that is a context the operator did not choose. Pass
    ``--include-secrets`` to print raw anyway.
    """
    raw_wanted = output is not None or include_secrets
    result = config_ops.config_backup(_resolve(target), include_secrets=raw_wanted)
    if output is not None:
        Path(output).write_text(result["config"])
        console.print(f"[green]Saved running config of {result['name']} -> {output}[/]")
        console.print(
            f"[yellow]{output} holds the RAW config — credential hashes, SNMP "
            f"communities, PSKs and RADIUS/TACACS keys included. Store it "
            f"accordingly.[/]"
        )
        return
    console.print(result["config"])
    _print_redaction(result)


@config_app.command("diff")
@cli_errors
def config_diff_cmd(
    config_file: Path,
    target: TargetOption = None,
    replace: bool = typer.Option(False, "--replace", help="Diff as a full replace"),
    include_secrets: IncludeSecretsOption = False,
) -> None:
    """Dry-run: show the diff a config file would produce (nothing is committed).

    Credential values in the diff are masked unless --include-secrets is passed.
    """
    text = read_config_text(config_file)
    result = config_ops.config_diff(
        _resolve(target), text, replace=replace, include_secrets=include_secrets
    )
    console.print(f"[bold]Diff ({result['mode']}, not committed):[/]")
    console.print(result["diff"] or "[dim](no changes)[/]")
    _print_redaction(result)


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
        # Through the GOVERNED twin, not the ops layer: the preview then runs the
        # same guard AND lands the same audit row as any other governed call. The
        # call comes BEFORE the banner so a refusal is never preceded by a green
        # "no changes will be committed" header it then contradicts.
        preview = gov.config_merge(
            config_text=text, target=target, revert_in=revert_in, dry_run=True
        )
        dry_run_preview(
            preview, operation="config_merge", detail=f"merge into {tgt.name}",
            parameters=_preview_params(preview),
        )
        _print_preview(preview)
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
        preview = gov.config_replace(
            config_text=text, target=target, revert_in=revert_in, dry_run=True
        )
        dry_run_preview(
            preview, operation="config_replace", detail=f"replace config of {tgt.name}",
            parameters=_preview_params(preview),
        )
        _print_preview(preview)
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
