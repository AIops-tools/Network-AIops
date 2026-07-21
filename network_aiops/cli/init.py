"""``network-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first network device: collects the
non-secret connection details into ``config.yaml`` (device name, NAPALM driver,
host, username, optional_args) and the login password into the *encrypted* store
(never plaintext on disk). Optionally configures a NetBox source-of-truth (url +
token, token stored encrypted as ``netbox-token``). Designed to be run on a
terminal; everything it needs is prompted with sensible defaults.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from network_aiops.cli._common import cli_errors, console
from network_aiops.config import CONFIG_DIR, CONFIG_FILE, SUPPORTED_DRIVERS
from network_aiops.secretstore import NETBOX_TOKEN_NAME, SecretStore, resolve_master_password


def _load_existing() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}


def _write_config(devices: list[dict], netbox: dict | None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    data: dict = {"devices": devices}
    if netbox:
        data["netbox"] = netbox
    CONFIG_FILE.write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")


def _prompt_driver() -> str:
    options = "/".join(SUPPORTED_DRIVERS)
    while True:
        driver = typer.prompt(f"NAPALM driver ({options})", default="ios").strip()
        if driver in SUPPORTED_DRIVERS:
            return driver
        console.print(f"[yellow]'{driver}' is not supported. Choose one of: {options}[/]")


def _prompt_optional_args() -> dict:
    """Collect NAPALM optional_args (port / transport / enable secret)."""
    optional_args: dict = {}
    port = typer.prompt("SSH/NETCONF port (Enter for driver default)", default="").strip()
    if port:
        try:
            optional_args["port"] = int(port)
        except ValueError:
            console.print("[yellow]Port must be a number; skipping.[/]")
    transport = typer.prompt(
        "Transport (e.g. ssh; Enter to skip)", default=""
    ).strip()
    if transport:
        optional_args["transport"] = transport
    if typer.confirm("Set an enable/secret password (optional_args.secret)?", default=False):
        secret = getpass.getpass("Enable secret (hidden): ")
        if secret:
            optional_args["secret"] = secret
            console.print(
                "[dim]Note: optional_args.secret is stored in config.yaml; keep the "
                "dir chmod 700.[/]"
            )
    return optional_args


@cli_errors
def init_cmd() -> None:
    """Interactively set up your first network device connection."""
    console.print("[bold cyan]Network AIops — setup wizard[/]")
    console.print(
        "This collects connection details (saved to config.yaml) and your device "
        "login password (saved [bold]encrypted[/] to secrets.enc).\n"
    )

    console.print("[bold]Step 1 — master password[/]")
    console.print(
        "[dim]Encrypts secrets.enc. You'll set it via the "
        "NETWORK_AIOPS_MASTER_PASSWORD env var for non-interactive/MCP use.[/]"
    )
    password = resolve_master_password(confirm_if_new=True)
    store = SecretStore.unlock(password)

    raw = _load_existing()
    devices = list(raw.get("devices", []))
    existing_names = {d.get("name") for d in devices}

    while True:
        console.print("\n[bold]Step 2 — add a device[/]")
        name = typer.prompt("Device name (e.g. core-sw1)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            devices = [d for d in devices if d.get("name") != name]

        driver = _prompt_driver()
        host = typer.prompt("Host (management IP or FQDN)").strip()
        username = typer.prompt("Username").strip()
        optional_args = _prompt_optional_args()

        secret = getpass.getpass(
            f"Login password for '{name}' (hidden, Enter to skip for key-auth): "
        )
        if secret:
            store = store.set(name, secret)

        entry: dict = {"name": name, "driver": driver, "host": host, "username": username}
        if optional_args:
            entry["optional_args"] = optional_args
        devices.append(entry)
        existing_names.add(name)
        _write_config(devices, raw.get("netbox"))
        suffix = "(password stored encrypted)" if secret else "(no password — key auth)"
        console.print(f"[green]✓ Saved device '{name}' {suffix}.[/]")

        if not typer.confirm("\nAdd another device?", default=False):
            break

    # ── Optional NetBox source-of-truth ──────────────────────────────────
    console.print("\n[bold]Step 3 — NetBox (optional source-of-truth)[/]")
    netbox = raw.get("netbox")
    if typer.confirm("Configure a NetBox connection?", default=False):
        url = typer.prompt("NetBox base URL (e.g. https://netbox.example.com)").strip()
        token = getpass.getpass("NetBox API token (hidden): ")
        if token:
            store = store.set(NETBOX_TOKEN_NAME, token)
        netbox = {"url": url}
        _write_config(devices, netbox)
        console.print("[green]✓ Saved NetBox config (token stored encrypted).[/]")

    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export NETWORK_AIOPS_MASTER_PASSWORD=... in your shell profile "
        "so the MCP server and CLI can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (network-aiops doctor)?", default=True):
        from network_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
