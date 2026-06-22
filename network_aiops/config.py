"""Configuration management for network-aiops.

Loads connection targets (network devices) from a YAML config file. Each device
declares a NAPALM ``driver`` (ios / nxos / nxos_ssh / iosxr / eos / junos), a
``host``, a ``username``, and optional ``optional_args`` (port, secret,
transport). Passwords are NOT stored here — they live in ``~/.network-aiops/.env``
as ``NETWORK_<TARGET_UPPER>_PASSWORD``. An optional ``netbox`` block (url +
token) enables source-of-truth lookups; the NetBox token lives in the same
``.env`` as ``NETWORK_NETBOX_TOKEN``.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".network-aiops"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

_log = logging.getLogger("network-aiops.config")

# NAPALM core drivers this skill officially tests / documents.
SUPPORTED_DRIVERS = ("ios", "nxos", "nxos_ssh", "iosxr", "eos", "junos")


def _check_dir_permissions() -> None:
    """Warn if the config dir is accessible beyond the owner (should be 700)."""
    if not CONFIG_DIR.exists():
        return
    try:
        mode = CONFIG_DIR.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            _log.warning(
                "Security warning: %s has permissions %s (should be 700). "
                "Run: chmod 700 %s",
                CONFIG_DIR,
                oct(stat.S_IMODE(mode)),
                CONFIG_DIR,
            )
    except OSError:
        pass


def _load_env() -> None:
    """Load ~/.network-aiops/.env so per-device passwords are available."""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)


_check_dir_permissions()
_load_env()


def password_env_var(target_name: str) -> str:
    """Return the env var name holding a device's password.

    ``core-sw1`` → ``NETWORK_CORE_SW1_PASSWORD``. Non-alphanumeric characters in
    the name become underscores so it is a valid shell identifier.
    """
    safe = "".join(c if c.isalnum() else "_" for c in target_name).upper()
    return f"NETWORK_{safe}_PASSWORD"


@dataclass(frozen=True)
class TargetConfig:
    """A network device connection target.

    ``driver`` is a NAPALM driver name (see ``SUPPORTED_DRIVERS``). ``host`` is
    the management IP or FQDN. ``optional_args`` is passed verbatim to NAPALM
    (e.g. ``{"port": 830, "secret": "enable-pw", "transport": "ssh"}``). The
    login password is resolved from the environment, never stored here.
    """

    name: str
    driver: str = "ios"
    host: str = ""
    username: str = ""
    optional_args: dict = field(default_factory=dict)

    def password(self) -> str:
        """Resolve the device password from the environment (may be empty)."""
        return os.environ.get(password_env_var(self.name), "")


@dataclass(frozen=True)
class NetBoxConfig:
    """Optional NetBox source-of-truth connection.

    ``url`` is the NetBox base URL; the API token is read from the environment
    (``NETWORK_NETBOX_TOKEN``) and never stored in config.yaml.
    """

    url: str

    def token(self) -> str:
        return os.environ.get("NETWORK_NETBOX_TOKEN", "")


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()
    netbox: NetBoxConfig | None = None

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError(
                "No devices configured. Add a 'devices:' list to "
                "~/.network-aiops/config.yaml"
            )
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML.

    Returns an empty config (no devices) when no file exists — the CLI/doctor
    then prints a teaching message rather than crashing.
    """
    path = config_path or CONFIG_FILE
    if not path.exists():
        return AppConfig()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=d["name"],
            driver=d.get("driver", "ios"),
            host=d.get("host", ""),
            username=d.get("username", ""),
            optional_args=dict(d.get("optional_args", {}) or {}),
        )
        for d in raw.get("devices", [])
    )

    netbox = None
    nb_raw = raw.get("netbox")
    if isinstance(nb_raw, dict) and nb_raw.get("url"):
        netbox = NetBoxConfig(url=str(nb_raw["url"]))

    return AppConfig(targets=targets, netbox=netbox)
