"""Environment and connectivity diagnostics for network-aiops."""

from __future__ import annotations

from rich.console import Console

from network_aiops.config import CONFIG_FILE, load_config, password_env_var

_console = Console()


def run_doctor(skip_auth: bool = False) -> int:
    """Check config and (optionally) device/NetBox reachability.

    Returns a process exit code: 0 healthy, 1 problems found. Connectivity
    failures are reported as status, never raised as tracebacks (a doctor must
    survive the thing it diagnoses being unhealthy).
    """
    problems = 0

    if CONFIG_FILE.exists():
        _console.print(f"[green]✓ Config file present: {CONFIG_FILE}[/]")
    else:
        _console.print(
            f"[yellow]! No config file ({CONFIG_FILE}); add a 'devices:' list.[/]"
        )

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — report, do not crash
        _console.print(f"[red]✗ Config load failed: {exc}[/]")
        return 1

    if not config.targets:
        _console.print("[yellow]! No devices configured.[/]")
        problems += 1
    else:
        _console.print(f"[green]✓ {len(config.targets)} device(s) configured[/]")
        for t in config.targets:
            var = password_env_var(t.name)
            present = "set" if t.password() else "MISSING"
            _console.print(f"  [dim]{t.name} ({t.driver}@{t.host}) — {var}: {present}[/]")

    if config.netbox is not None:
        present = "set" if config.netbox.token() else "MISSING"
        _console.print(f"[green]✓ NetBox configured: {config.netbox.url} (token {present})[/]")

    if skip_auth:
        _console.print("[dim]Skipping connectivity check (--skip-auth).[/]")
        return 1 if problems else 0

    from network_aiops.connection import device_session, netbox_api
    from network_aiops.ops._shared import getter

    for target in config.targets:
        try:
            with device_session(target) as dev:
                facts = getter(target.driver, "get_facts", dev.get_facts)
            _console.print(
                f"[green]✓ Reachable '{target.name}' "
                f"(model {facts.get('model', '?')}, os {facts.get('os_version', '?')})[/]"
            )
        except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
            _console.print(f"[red]✗ Connect to '{target.name}' failed: {exc}[/]")
            problems += 1

    if config.netbox is not None:
        try:
            api = netbox_api(config.netbox)
            api.status()
            _console.print("[green]✓ NetBox reachable[/]")
        except Exception as exc:  # noqa: BLE001
            _console.print(f"[red]✗ NetBox check failed: {exc}[/]")
            problems += 1

    return 1 if problems else 0
