"""Shared helpers for network-aiops CLI sub-modules."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console

if TYPE_CHECKING:
    from network_aiops.connection import ConnectionManager

console = Console()

# ─── Shared Option types ───────────────────────────────────────────────────

TargetOption = Annotated[
    str | None, typer.Option("--target", "-t", help="Device name from config")
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Preview the diff without committing")
]
OutputOption = Annotated[
    Path | None, typer.Option("--output", "-o", help="Write output to a file")
]


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback.

    ``PolicyDenied``/``BudgetExceeded`` are raised by ``@governed_tool`` OUTSIDE
    the tool body, so ``tool_errors`` never sees them and they never arrive as
    an ``{"error": ...}`` dict. Their message is the teaching text (which
    approver to set, which budget was hit) — without them here a refusal
    reaches the CLI as a traceback instead.
    """
    from network_aiops.connection import NetworkApiError
    from network_aiops.governance import BudgetExceeded, PolicyDenied

    return (NetworkApiError, PolicyDenied, BudgetExceeded, KeyError, OSError, ValueError)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            message = str(e)
            if isinstance(e, KeyError):
                message = f"Missing required key: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


def get_manager(config_path: Path | None = None) -> ConnectionManager:
    """Return a ConnectionManager built from config."""
    from network_aiops.config import load_config
    from network_aiops.connection import ConnectionManager

    return ConnectionManager(load_config(config_path))


def read_config_text(path: Path) -> str:
    """Read a config-snippet file for merge/replace/diff."""
    return path.read_text()


def dry_run_print(*, operation: str, detail: str, parameters: dict | None = None) -> None:
    """Print a dry-run preview header (the diff is printed by the caller)."""
    console.print("\n[bold magenta][DRY-RUN] No changes will be committed.[/]")
    console.print(f"[magenta]  Operation: {operation}[/]")
    console.print(f"[magenta]  Detail:    {detail}[/]")
    for k, v in (parameters or {}).items():
        console.print(f"[magenta]  Param:     {k} = {v}[/]")
    console.print("[magenta]  Run without --dry-run to commit.[/]\n")


def dry_run_preview(
    preview: Any, *, operation: str, detail: str, parameters: dict | None = None
) -> None:
    """Render a GOVERNED dry-run result as the human-readable DRY-RUN banner.

    ``preview`` must come from calling the governed tool with ``dry_run=True``,
    so every guard it carries has already run against the real target. A refusal
    arrives as ``{"error": ...}`` (``tool_errors`` flattens the exception) — it is
    printed like any other CLI error and exits non-zero, exactly as the real
    write would. Printing a green banner for a call that is about to be refused
    is the preview being wrong, not merely incomplete.

    On the allowed path the banner is byte-for-byte what it always was: routing
    through the governed call buys the guard and the audit row, not a new
    serialization.
    """
    if isinstance(preview, dict) and preview.get("error"):
        console.print(f"[red]Error: {preview['error']}[/]")
        raise typer.Exit(1)
    dry_run_print(operation=operation, detail=detail, parameters=parameters)


def double_confirm(action: str, resource: str) -> None:
    """Require two confirmations for a destructive operation."""
    console.print(f"[bold yellow]⚠️  About to: {action} '{resource}'[/]")
    typer.confirm(f"Confirm 1/2: {action} '{resource}'?", abort=True)
    typer.confirm(
        f"Confirm 2/2: really {action} '{resource}'? This may be disruptive.",
        abort=True,
    )
