<!-- mcp-name: io.github.AIops-tools/network-aiops -->
# network-aiops (preview)

> **Disclaimer**: This is a community-maintained open-source project and is **not
> affiliated with, endorsed by, or sponsored by Cisco, Arista, Juniper, NetBox
> Labs, or any network vendor.** Vendor and product names are trademarks of their
> respective owners. Source code is publicly auditable at
> [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
> under the MIT license.

Governed multi-vendor network device operations for AI agents — **13 MCP tools**,
every one wrapped with the bundled `@governed_tool` harness: a local unified audit
log under `~/.network-aiops/`, policy engine, token/runaway budget guard,
undo-token recording, and graduated-autonomy risk tiers.

Devices are reached over [NAPALM](https://napalm.readthedocs.io/); an optional
NetBox block adds source-of-truth lookups.

> **Standalone**: the governance harness is bundled in the package
> (`network_aiops.governance`) — network-aiops has no external skill-family
> dependency. Preview: common device operations, not yet exhaustive.

## What works

Read device facts/interfaces/IP/BGP/LLDP/ARP, back up the running config, dry-run
a config diff, and merge/replace/rollback config — across the five core NAPALM
platforms below. Optional NetBox lookups confirm intended state before a change.

## Supported devices

| Platform | NAPALM driver | Transport |
|----------|---------------|-----------|
| Cisco IOS / IOS-XE | `ios` | SSH |
| Cisco Nexus NX-OS | `nxos` (NX-API) / `nxos_ssh` (SSH) | HTTPS / SSH |
| Cisco IOS-XR | `iosxr` | SSH (XML agent) |
| Arista EOS | `eos` | eAPI (HTTPS) |
| Juniper Junos | `junos` | NETCONF (SSH) |

Additional platforms (Nokia SR OS / SR Linux, Huawei VRP, etc.) are reachable via
NAPALM **community drivers** but are **not officially tested here**. Need one?
See [Contributing](#contributing--feature-requests).

## Supported actions

| Action | Tool | R/W | Risk |
|--------|------|:---:|:----:|
| Device facts (hostname/vendor/model/OS/serial/uptime) | `device_facts` | R | low |
| Interfaces (up/down, speed, description) | `get_interfaces` | R | low |
| Interface IP addresses | `get_interfaces_ip` | R | low |
| BGP neighbors | `get_bgp_neighbors` | R | low |
| LLDP neighbors | `get_lldp_neighbors` | R | low |
| ARP table | `get_arp_table` | R | low |
| Back up running config | `config_backup` | R | low |
| Diff a candidate (dry-run) | `config_diff` | R | low |
| Merge config + commit | `config_merge` | W | medium |
| Replace full config + commit | `config_replace` | W | **high** |
| Roll back last commit | `config_rollback` | W | medium |
| NetBox list devices | `netbox_list_devices` | R | low |
| NetBox get device | `netbox_get_device` | R | low |

## Quick Start

```bash
uv tool install network-aiops
network-aiops doctor
network-aiops device facts -t core-sw1
network-aiops config backup -t core-sw1 -o core-sw1.cfg
```

Create `~/.network-aiops/config.yaml`:

```yaml
devices:
  - name: core-sw1            # used as -t core-sw1
    driver: eos               # ios | nxos | nxos_ssh | iosxr | eos | junos
    host: 10.0.0.1
    username: admin
    optional_args:            # passed verbatim to NAPALM (optional)
      secret: enable-pw       # enable/secret
      port: 443
# Optional source-of-truth:
netbox:
  url: https://netbox.example.com
```

Put secrets in `~/.network-aiops/.env` (chmod 600) — never in config.yaml:

```bash
NETWORK_CORE_SW1_PASSWORD=...     # NETWORK_<TARGET_UPPER>_PASSWORD
NETWORK_NETBOX_TOKEN=...
```

## MCP

```jsonc
{
  "command": "network-aiops",
  "args": ["mcp"],
  "env": { "NETWORK_AIOPS_CONFIG": "~/.network-aiops/config.yaml" }
}
```

## Audit & Safety

- Every tool call is logged to `~/.network-aiops/audit.db` (local SQLite;
  relocate with `NETWORK_AIOPS_HOME`).
- `config_merge` / `config_replace` capture the pre-change running config and
  record an inverse `config_replace`-to-backup undo descriptor.
- `config_replace` is `risk_level=high`; CLI destructive commands (`config
  merge/replace/rollback`) require double confirmation and support `--dry-run`
  (which prints the diff without committing).
- All device text passes through `sanitize()` (prompt-injection defense).

See `skills/network-aiops/SKILL.md` and `SECURITY.md` for details.

## Companion Skills

| If you want… | Use |
|--------------|-----|
| Network device config / facts (Cisco/Arista/Juniper) | **network-aiops** (this) |
| Kubernetes cluster operations | a cluster ops skill |
| Hypervisor VM lifecycle | a hypervisor ops skill |

## Contributing & feature requests

This is a preview — coverage is intentionally focused. **Need a device or action
that isn't here yet?** Open an issue or pull request at
[github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops/issues)
— contributions, feature requests, and comments are all welcome.

## License

MIT — [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
