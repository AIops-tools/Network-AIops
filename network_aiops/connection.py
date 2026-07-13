"""Connection management for network devices (NAPALM) and optional NetBox.

NAPALM is not a persistent session: a driver instance is opened, used, and
closed per call. ``device_session()`` is a context manager that builds the
right driver from a :class:`TargetConfig`, opens it, yields the live driver, and
always closes it. Nothing risky is cached.

All NAPALM / driver failures are translated centrally into ``NetworkApiError``
with a teaching message — REST/SSH-wrapper skills should translate errors at the
connection layer from the first version, not let users hit raw tracebacks.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from network_aiops.config import (
    SUPPORTED_DRIVERS,
    AppConfig,
    NetBoxConfig,
    TargetConfig,
    load_config,
)

# Default NAPALM connection/command timeout (seconds). Without it a wedged
# device can hang a session indefinitely. Merged into every driver's
# optional_args; a user-provided value in the target's optional_args wins.
_DEFAULT_OPTIONAL_ARGS: dict[str, Any] = {"timeout": 60}


class NetworkApiError(Exception):
    """A device or NetBox call failed; carries a teaching message + optional host."""

    def __init__(self, message: str, *, host: str = "", driver: str = "") -> None:
        self.host = host
        self.driver = driver
        super().__init__(message)


def _napalm():
    """Import NAPALM lazily so the package imports without it installed in CI."""
    try:
        from napalm import get_network_driver

        return get_network_driver
    except ImportError as exc:  # pragma: no cover - exercised only without napalm
        raise NetworkApiError(
            "The 'napalm' package is not installed. Install it with "
            "'uv tool install network-aiops' (it is a declared dependency) or "
            "'pip install napalm'."
        ) from exc


def _driver_for(target: TargetConfig):
    """Resolve and validate the NAPALM driver class for a target."""
    if target.driver not in SUPPORTED_DRIVERS:
        raise NetworkApiError(
            f"Driver '{target.driver}' for device '{target.name}' is not in the "
            f"officially supported set ({', '.join(SUPPORTED_DRIVERS)}). NAPALM "
            f"community drivers (Nokia SR OS, Huawei VRP, etc.) may still work but "
            f"are untested here — please request support via a GitHub issue/PR.",
            host=target.host,
            driver=target.driver,
        )
    get_network_driver = _napalm()
    try:
        return get_network_driver(target.driver)
    except Exception as exc:  # noqa: BLE001 — any driver-resolution failure
        raise NetworkApiError(
            f"Could not load NAPALM driver '{target.driver}' for '{target.name}': "
            f"{exc}. Supported drivers: {', '.join(SUPPORTED_DRIVERS)}.",
            host=target.host,
            driver=target.driver,
        ) from exc


def _translate(exc: Exception, target: TargetConfig) -> NetworkApiError:
    """Map a NAPALM/driver exception to a teaching ``NetworkApiError``."""
    name = type(exc).__name__
    detail = str(exc).strip()[:200]
    host = target.host or target.name
    if name in ("ConnectionException", "ConnectAuthError", "SSHException"):
        return NetworkApiError(
            f"Could not connect/authenticate to '{target.name}' ({host}). Check the "
            f"host/port, the username, and that {target.driver and target.driver} "
            f"password env var is set (see 'network-aiops doctor'). {detail}",
            host=host,
            driver=target.driver,
        )
    if name == "CommandErrorException":
        return NetworkApiError(
            f"The device '{target.name}' rejected a command. The platform may not "
            f"support this operation, or the account lacks privilege. {detail}",
            host=host,
            driver=target.driver,
        )
    if isinstance(exc, NotImplementedError):
        return NetworkApiError(
            f"Operation not supported by the '{target.driver}' NAPALM driver for "
            f"'{target.name}'. {detail}",
            host=host,
            driver=target.driver,
        )
    return NetworkApiError(
        f"Device operation on '{target.name}' ({host}) failed: {detail}",
        host=host,
        driver=target.driver,
    )


@contextmanager
def device_session(target: TargetConfig) -> Iterator[Any]:
    """Open a NAPALM connection to ``target``, yield the driver, always close it.

    NAPALM connections are short-lived: the caller does its getters/config work
    inside the ``with`` block and the connection is closed on exit. Connection
    and command failures are translated to ``NetworkApiError``.
    """
    driver_cls = _driver_for(target)
    optional_args = {**_DEFAULT_OPTIONAL_ARGS, **(target.optional_args or {})}
    device = driver_cls(
        hostname=target.host,
        username=target.username,
        password=target.password(),
        optional_args=optional_args,
    )
    try:
        device.open()
    except Exception as exc:  # noqa: BLE001 — translate any open failure
        raise _translate(exc, target) from exc
    try:
        yield device
    except NetworkApiError:
        raise
    except Exception as exc:  # noqa: BLE001 — translate any in-session failure
        raise _translate(exc, target) from exc
    finally:
        try:
            device.close()
        except Exception:  # noqa: BLE001 — close must not mask the real error
            pass


def netbox_api(netbox: NetBoxConfig | None) -> Any:
    """Return a configured pynetbox API client, or raise a teaching error.

    Degrades gracefully: a clear ``NetworkApiError`` when NetBox is not
    configured or the token/library is missing, instead of an opaque traceback.
    """
    if netbox is None:
        raise NetworkApiError(
            "NetBox is not configured. Add a 'netbox: {url: ...}' block to "
            "~/.network-aiops/config.yaml and store the API token encrypted with "
            "'network-aiops secret set netbox-token' (or 'network-aiops init') "
            "to use source-of-truth lookups."
        )
    token = netbox.token()
    if not token:
        raise NetworkApiError(
            "NetBox token missing. Store it encrypted with "
            "'network-aiops secret set netbox-token' (or run 'network-aiops init')."
        )
    try:
        import pynetbox
    except ImportError as exc:  # pragma: no cover
        raise NetworkApiError(
            "The 'pynetbox' package is not installed (declared dependency)."
        ) from exc
    try:
        return pynetbox.api(netbox.url, token=token)
    except Exception as exc:  # noqa: BLE001
        raise NetworkApiError(
            f"Could not initialise the NetBox client for {netbox.url}: {exc}"
        ) from exc


class ConnectionManager:
    """Resolves targets and the NetBox client from an AppConfig."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        return cls(config or load_config())

    @property
    def config(self) -> AppConfig:
        return self._config

    def target(self, target_name: str | None = None) -> TargetConfig:
        """Return a target by name, or the default (first) device."""
        if target_name:
            return self._config.get_target(target_name)
        return self._config.default_target

    def session(self, target_name: str | None = None) -> AbstractContextManager[Any]:
        """Return a ``device_session`` context manager for a target."""
        return device_session(self.target(target_name))

    def netbox(self) -> Any:
        """Return a pynetbox client (or raise a teaching NetworkApiError)."""
        return netbox_api(self._config.netbox)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]
