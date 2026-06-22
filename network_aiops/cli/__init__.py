"""CLI package for network-aiops.

Re-exports ``app`` so the pyproject entry point
``network-aiops = "network_aiops.cli:app"`` works unchanged.
"""

from network_aiops.cli._root import app

__all__ = ["app"]
