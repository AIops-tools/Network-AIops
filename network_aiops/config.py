"""Configuration management for network-aiops.

Loads connection targets (network devices) from a YAML config file. Each device
declares a NAPALM ``driver`` (ios / nxos / nxos_ssh / iosxr / eos / junos), a
``host``, a ``username``, and optional ``optional_args`` (port, secret,
transport). Secrets are NEVER stored here and never on disk in plaintext: both
the per-device login password and the optional NetBox API token live in the
encrypted store ``~/.network-aiops/secrets.enc`` (see
:mod:`network_aiops.secretstore`). Device passwords are keyed by the device
target name; the NetBox token is keyed by the reserved name ``netbox-token``.

For backward compatibility the legacy plaintext env vars
(``NETWORK_<TARGET_UPPER>_PASSWORD`` and ``NETWORK_NETBOX_TOKEN``, e.g. from an
old ``~/.network-aiops/.env``) are still honoured as a fallback, with a warning
nudging migration to the encrypted store.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from network_aiops.governance.paths import ops_home
from network_aiops.secretstore import (
    NETBOX_TOKEN_NAME,
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# Legacy env-var prefix/suffix; also used by the migration helper.
SECRET_ENV_PREFIX = "NETWORK_"  # nosec B105 — env var prefix, not a secret
SECRET_ENV_SUFFIX = "_PASSWORD"  # nosec B105 — env var suffix, not a secret
NETBOX_TOKEN_ENV = "NETWORK_NETBOX_TOKEN"  # nosec B105 — env var name, not a secret

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


def _resolve_password(name: str) -> str:
    """Resolve a device's login password: encrypted store first, then legacy env.

    Returns "" when no secret is found anywhere — an empty password is valid for
    key-based SSH auth (configured via ``optional_args``), so a missing password
    is a warning (surfaced by ``network-aiops doctor``), not a hard error.
    """
    if has_store():
        try:
            return get_secret(name)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as a missing-credential
            # error, sending the operator to add something already there.
            # MasterPasswordError subclasses SecretStoreError, so the broad
            # catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # fall through to legacy env var
    legacy = os.environ.get(password_env_var(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'network-aiops secret migrate'.",
            password_env_var(name),
        )
        return legacy
    return ""


def _resolve_netbox_token() -> str:
    """Resolve the NetBox API token: encrypted store first, then legacy env.

    Returns "" when not found (NetBox is optional; the connection layer raises a
    teaching error if a NetBox call is attempted without a token).
    """
    if has_store():
        try:
            return get_secret(NETBOX_TOKEN_NAME)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as a missing-credential
            # error, sending the operator to add something already there.
            # MasterPasswordError subclasses SecretStoreError, so the broad
            # catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass
    legacy = os.environ.get(NETBOX_TOKEN_ENV)
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'network-aiops secret migrate'.",
            NETBOX_TOKEN_ENV,
        )
        return legacy
    return ""


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
        """Resolve the device password from the encrypted store (or legacy env).

        May be empty (valid for key-based SSH auth).
        """
        return _resolve_password(self.name)


@dataclass(frozen=True)
class NetBoxConfig:
    """Optional NetBox source-of-truth connection.

    ``url`` is the NetBox base URL; the API token comes from the encrypted store
    (reserved name ``netbox-token``) or a legacy env var, never config.yaml.
    """

    url: str

    def token(self) -> str:
        return _resolve_netbox_token()


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
