"""network-aiops — governed multi-vendor network device operations for AI agents.

Standalone and self-contained: the governance harness (audit, token budget,
undo-token recording, graduated risk tiers, output sanitize) is
bundled under ``network_aiops.governance`` — this package has no external
skill-family dependency. Devices are reached over NAPALM (Cisco IOS/IOS-XE,
Nexus NX-OS, IOS-XR, Arista EOS, Juniper Junos); an optional NetBox block adds
source-of-truth lookups. Preview: not yet full-coverage.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("network-aiops")
except PackageNotFoundError:  # running from an uninstalled source tree
    __version__ = "0.0.0+unknown"
