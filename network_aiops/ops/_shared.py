"""Shared helpers for the ops layer.

``getter()`` invokes a NAPALM getter and turns a per-driver
``NotImplementedError`` into a teaching ``NetworkApiError`` centrally, so an
agent sees "not supported by the <driver> driver" rather than a raw traceback.
``s()`` sanitizes any device-returned text before it reaches the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from network_aiops.connection import NetworkApiError
from network_aiops.governance import sanitize


def s(value: Any, limit: int = 256) -> str:
    """Sanitize a scalar device value to a bounded, control-char-free string."""
    return sanitize(str(value if value is not None else ""), limit)


def getter(driver: str, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a NAPALM getter, translating NotImplementedError per-driver.

    Args:
        driver: NAPALM driver name (for the teaching message).
        name: human-readable getter name (e.g. "get_bgp_neighbors").
        fn: the bound NAPALM getter to call.
    """
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        raise NetworkApiError(
            f"'{name}' is not supported by the '{driver}' NAPALM driver. "
            f"Try a different getter, or request support via a GitHub issue/PR.",
            driver=driver,
        ) from exc
