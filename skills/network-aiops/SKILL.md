---
name: network-aiops
description: >
  Use this skill whenever the user needs to operate a network device — read device facts, interfaces, IP addresses, BGP/LLDP neighbors, and ARP tables, back up a switch/router config, diff a candidate config (dry-run), and merge/replace/rollback config — across Cisco IOS/IOS-XE, Nexus NX-OS, IOS-XR, Arista EOS, and Juniper Junos via NAPALM. An optional NetBox block adds source-of-truth lookups.
  Always use this skill for "back up switch config", "show bgp neighbors", "diff network config", "push config to router", "show interfaces on the switch", or tasks mentioning "cisco", "arista", "juniper", "nexus", "ios-xr", or "napalm".
  Do NOT use when the target is not a NAPALM-supported network device (Kubernetes clusters, hypervisor VMs, and cloud consoles are out of scope — route those elsewhere).
  Preview — common multi-vendor device operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers).
installer:
  kind: uv
  package: network-aiops
argument-hint: "[device name or describe your network task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["NETWORK_AIOPS_CONFIG"],"bins":["network-aiops"],"config":["~/.network-aiops/config.yaml"]},"optional":{"env":["NETWORK_AIOPS_HOME","NETWORK_NETBOX_TOKEN"]},"primaryEnv":"NETWORK_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/Network-AIops","emoji":"🛜","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed network device operations (preview) over NAPALM. The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.network-aiops/ (relocatable via NETWORK_AIOPS_HOME).
  Credentials: passwords are read from ~/.network-aiops/.env as NETWORK_<TARGET_UPPER>_PASSWORD (per device), and the optional NetBox token from NETWORK_NETBOX_TOKEN. config.yaml holds only device names, drivers, hosts, usernames, and NAPALM optional_args — never secrets. The state dir ~/.network-aiops should be chmod 700 and .env chmod 600.
  Destructive operations (config merge, config replace, config rollback) require double confirmation at the CLI layer and support --dry-run (which prints the diff without committing). All write tools pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). config_merge and config_replace capture the pre-change running config and record an inverse config_replace-to-backup undo descriptor; config_rollback records none, and config_replace is risk_level=high.
  Webhooks: none — no outbound network calls beyond the configured device sessions and the optional NetBox API.
  TLS: NAPALM driver transports (eAPI/NX-API HTTPS, NETCONF/SSH) follow the device's own certificate/SSH host-key settings; the skill does not weaken them.
  Transitive dependencies: napalm (device drivers), pynetbox (optional source-of-truth), typer/rich (CLI), pyyaml/python-dotenv (config), and the MCP SDK. No post-install scripts or background services.
---

# Network AIops (preview)

> **Disclaimer**: This is a community-maintained open-source project and is **not affiliated with, endorsed by, or sponsored by Cisco, Arista, Juniper, NetBox Labs, or any network vendor.** Vendor and product names are trademarks of their respective owners. Source code is publicly auditable at [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops) under the MIT license.

Governed multi-vendor network device operations — **13 MCP tools**, every one wrapped with the bundled `@governed_tool` harness: a local unified audit log under `~/.network-aiops/`, policy engine, token/runaway budget guard, undo-token recording, and graduated-autonomy risk tiers. Devices are reached over NAPALM; an optional NetBox block adds source-of-truth lookups.

> **Standalone**: the governance harness is bundled in the package (`network_aiops.governance`) — network-aiops has no external skill-family dependency. Preview: common operations, not yet exhaustive.

## What This Skill Does

| Category | Tools | Count | Read or Write |
|----------|-------|:-----:|:-------------:|
| **Device facts** | facts, interfaces, interface IPs, BGP, LLDP, ARP | 6 | 6 read |
| **Config** | backup, diff (dry-run), merge, replace, rollback | 5 | 2 read / 3 write |
| **NetBox** | list devices, get device | 2 | 2 read |

## Quick Install

```bash
uv tool install network-aiops
network-aiops doctor          # checks config + per-device password env vars
```

## Supported Devices

| Platform | NAPALM driver | Transport |
|----------|---------------|-----------|
| Cisco IOS / IOS-XE | `ios` | SSH |
| Cisco Nexus NX-OS | `nxos` (NX-API) / `nxos_ssh` (SSH) | HTTPS / SSH |
| Cisco IOS-XR | `iosxr` | SSH (XML agent) |
| Arista EOS | `eos` | eAPI (HTTPS) |
| Juniper Junos | `junos` | NETCONF (SSH) |

Other platforms (Nokia SR OS / SR Linux, Huawei VRP, etc.) are reachable via NAPALM **community drivers** but are **not officially tested here** — see [Contributing](#contributing--request-a-device-or-feature).

## When to Use This Skill

- Inspect device facts, interfaces, IP addressing, BGP/LLDP neighbors, ARP entries
- Back up a switch/router running config to a file
- Dry-run a config change as a diff before committing
- Merge a config snippet, replace the full config, or roll back the last commit
- Cross-check intended state in NetBox before pushing a change

**Do NOT use when** the target is not a NAPALM-supported network device (Kubernetes clusters, hypervisor VMs, and cloud-provider consoles are out of scope for this skill).

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| Network device config / facts (Cisco/Arista/Juniper) | **network-aiops** (this skill) |
| Kubernetes cluster operations | a cluster ops skill |
| Hypervisor VM lifecycle (power, snapshot, migrate) | a hypervisor ops skill |

## Supported Actions

| Tool | R/W | Risk | Driver support |
|------|:---:|:----:|----------------|
| `device_facts` | R | low | all 5 |
| `get_interfaces` | R | low | all 5 |
| `get_interfaces_ip` | R | low | all 5 |
| `get_bgp_neighbors` | R | low | all 5 (varies by feature) |
| `get_lldp_neighbors` | R | low | all 5 |
| `get_arp_table` | R | low | all 5 |
| `config_backup` | R | low | all 5 |
| `config_diff` (dry-run) | R | low | all 5 |
| `config_merge` | W | medium | all 5 |
| `config_replace` | W | **high** | ios/eos/junos/iosxr; nxos varies |
| `config_rollback` | W | medium | device-dependent rollback depth |
| `netbox_list_devices` | R | low | NetBox (optional) |
| `netbox_get_device` | R | low | NetBox (optional) |

A per-driver `NotImplementedError` becomes a teaching error ("not supported by the `<driver>` driver").

## Common Workflows

### Safely change a device config with a dry-run first

1. `network-aiops config backup -t core-sw1 -o core-sw1.cfg` → keep a known-good copy
2. `network-aiops config diff change.cfg -t core-sw1` → preview the diff (nothing committed)
3. `network-aiops config merge change.cfg -t core-sw1` (double confirm) → commit; the harness records a `config_replace`-to-backup undo descriptor
4. `network-aiops device interfaces -t core-sw1` → verify the result
5. **Failure branch**: if the connection fails (`Could not connect/authenticate`), run `network-aiops doctor` — it shows whether `NETWORK_CORE_SW1_PASSWORD` is set and whether the host/port is reachable; the skill never retries a denied auth.

### Diagnose a BGP/peering problem

1. `network-aiops device bgp -t edge-rtr` → find the down neighbor (`is_up=False`)
2. `network-aiops device interfaces -t edge-rtr` → confirm the uplink is up
3. `network-aiops device arp -t edge-rtr` → confirm L2/L3 reachability to the peer
4. **Failure branch**: if `get_bgp_neighbors` returns "not supported by the `<driver>` driver", the platform's NAPALM driver lacks that getter — fall back to `config_backup` and inspect the BGP stanza, and request the getter via a GitHub issue.

## Usage Mode

| Scenario | Recommended | Why |
|----------|:-----------:|-----|
| Local/small models (Ollama, Qwen) | **CLI** | fewer tokens than MCP |
| Cloud models (Claude, GPT) | Either | MCP gives structured JSON I/O |
| Automated pipelines | **MCP** | type-safe parameters, audited |

## MCP Tools (13 — 10 read, 3 write)

| Category | Tools | R/W |
|----------|-------|:---:|
| Facts | `device_facts`, `get_interfaces`, `get_interfaces_ip`, `get_bgp_neighbors`, `get_lldp_neighbors`, `get_arp_table` | Read |
| Config | `config_backup`, `config_diff` | Read |
| | `config_merge`, `config_replace`, `config_rollback` | Write |
| NetBox | `netbox_list_devices`, `netbox_get_device` | Read |

**Harness features that light up**: `config_merge` and `config_replace` capture the pre-change running config and pass an `undo=` lambda so the harness records an inverse descriptor (with `_undo_id`) that restores the captured config via `config_replace` — the device must support config replace for the undo to apply. `config_rollback` declares no undo; `config_replace` is tagged `risk_level=high`. `config_diff` is a pure dry-run (stage candidate → compare → discard). All 13 tools are audit-logged under `~/.network-aiops/` and pass through the policy pre-check + budget/runaway guard + graduated risk-tier gate. Avoid tight poll loops — the runaway breaker backs this up.

## CLI Quick Reference

```bash
network-aiops device facts [-t <device>]
network-aiops device interfaces [-t <device>]
network-aiops device bgp [-t <device>]
network-aiops device lldp [-t <device>]
network-aiops device arp [-t <device>]
network-aiops config backup [-t <device>] [-o <file>]
network-aiops config diff <file> [-t <device>] [--replace]
network-aiops config merge <file> [-t <device>] [--dry-run]      # double confirm
network-aiops config replace <file> [-t <device>] [--dry-run]    # HIGH RISK
network-aiops config rollback [-t <device>] [--dry-run]          # double confirm
network-aiops netbox list [--name <q>] [--limit N]
network-aiops netbox get <name>
network-aiops doctor
network-aiops mcp                                                # start MCP server (stdio)
```

See `references/cli-reference.md` for the full command list.

## Troubleshooting

### "Could not connect/authenticate to '<device>'"
The host/port, username, or password is wrong, or the device is unreachable. Run `network-aiops doctor` — it reports whether `NETWORK_<DEVICE_UPPER>_PASSWORD` is set and whether the device answers. For enable/secret, set it in `optional_args.secret`.

### "Operation not supported by the '<driver>' NAPALM driver"
That getter or config mode is not implemented for this platform. Try a different getter, or fall back to `config_backup` and inspect the relevant stanza. Request the capability via a GitHub issue/PR.

### "Driver '<x>' is not in the officially supported set"
Only `ios`, `nxos`, `nxos_ssh`, `iosxr`, `eos`, `junos` are tested here. Community drivers may work but are untested — request official support via a GitHub issue/PR.

### NetBox commands fail with "NetBox is not configured"
Add a `netbox: {url: ...}` block to `config.yaml` and set `NETWORK_NETBOX_TOKEN` in `~/.network-aiops/.env`. NetBox tools degrade gracefully when unconfigured.

### `config replace` failed mid-commit
The device may not support full config replace (some Nexus images do not). Use `config merge` for additive changes, or restore from your `config backup` file.

## Audit & Safety

All operations are automatically audited via the bundled `@governed_tool` decorator (`network_aiops.governance`):
- Every tool call logged to `~/.network-aiops/audit.db` (local SQLite audit DB; relocate with `NETWORK_AIOPS_HOME`)
- Policy rules enforced via `~/.network-aiops/rules.yaml` (deny rules, maintenance windows, risk tiers)
- Budget / runaway guard caps cumulative tool calls and wall-time, and trips on tight poll/retry loops
- Undo store records inverse descriptors for reversible writes (config merge/replace → restore captured running config)
- Graduated-autonomy risk tiers gate write operations (require a recorded approver for the highest tiers)

The harness is bundled in the package — no external dependency, no manual setup. See `references/setup-guide.md` for security details.

## Contributing — request a device or feature

This is a preview — coverage is intentionally focused. **Need a device (Nokia SR OS, Huawei VRP, …) or an action that isn't here yet?** Open an issue or pull request at [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops/issues) — feature requests, contributions, and comments are all welcome.

## License

MIT — [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
