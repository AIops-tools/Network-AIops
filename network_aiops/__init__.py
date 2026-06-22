"""network-aiops — governed multi-vendor network device operations for AI agents.

Standalone and self-contained: the governance harness (audit, token budget,
undo-token recording, graduated risk tiers, prompt-injection sanitize) is
bundled under ``network_aiops.governance`` — this package has no external
skill-family dependency. Devices are reached over NAPALM (Cisco IOS/IOS-XE,
Nexus NX-OS, IOS-XR, Arista EOS, Juniper Junos); an optional NetBox block adds
source-of-truth lookups. Preview: not yet full-coverage.
"""

__version__ = "0.1.0"
