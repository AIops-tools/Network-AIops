# Release Notes

## 0.1.0 (preview)

Initial preview release of **network-aiops** — governed multi-vendor network
device operations for AI agents.

- **13 MCP tools** (10 read / 3 write), every one wrapped with the bundled
  `@governed_tool` harness (audit, policy, token/runaway budget, undo-token
  recording, graduated risk tiers).
- Devices reached over **NAPALM**. Officially supported drivers: `ios`,
  `nxos`, `nxos_ssh`, `iosxr`, `eos`, `junos`.
- Read getters: device facts, interfaces, interface IPs, BGP neighbors, LLDP
  neighbors, ARP table, config backup, config diff (dry-run).
- Config writes: merge (medium), replace (high), rollback (medium). Merge and
  replace capture the pre-change running config and record a `config_replace`
  undo descriptor that restores it.
- Optional **NetBox** source-of-truth lookups (`netbox_list_devices`,
  `netbox_get_device`); degrade gracefully when not configured.
- CLI: `device facts/interfaces/bgp/lldp/arp`, `config backup/diff/merge/replace/rollback`,
  `netbox list/get`, `doctor`, `mcp`. Destructive config ops require double
  confirmation and `--dry-run`.
- Standalone: governance harness bundled under `network_aiops.governance`; no
  external skill-family dependency.
