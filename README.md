<!-- mcp-name: io.github.AIops-tools/network-aiops -->
# network-aiops

> **Disclaimer**: This is a community-maintained open-source project and is **not
> affiliated with, endorsed by, or sponsored by Cisco, Arista, Juniper, NetBox
> Labs, or any network vendor.** Vendor and product names are trademarks of their
> respective owners. Source code is publicly auditable at
> [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
> under the MIT license.

Governed multi-vendor network device operations for AI agents — **33 MCP tools**,
every one wrapped with the bundled `@governed_tool` harness: a local unified audit
log under `~/.network-aiops/`, policy engine, token/runaway budget guard,
undo-token recording, and graduated-autonomy risk tiers. Credentials (device
passwords + the NetBox token) are kept in an **encrypted store** (`secrets.enc`),
never plaintext on disk.

Devices are reached over [NAPALM](https://napalm.readthedocs.io/); an optional
NetBox block adds source-of-truth lookups.

> **Standalone**: the governance harness is bundled in the package
> (`network_aiops.governance`) — network-aiops has no external skill-family
> dependency. Coverage focuses on common device operations and is not yet exhaustive.

> **Verification status**: the test suite is mock-based; not yet validated against live
> devices — self-testable with cEOS / vMX / containerlab. See
> [docs/VERIFICATION.md](docs/VERIFICATION.md).

## What works

Read device facts, interfaces (+ counters/IP), BGP/LLDP neighbors (summary and
detail), ARP/MAC tables, VLANs, route lookups, hardware environment, optics, NTP,
users, SNMP info, VRFs, and an aggregated `device_health`; run read-only **RCA
diagnostics** that flag down/erroring/flapping interfaces and unhealthy BGP
neighbors — each finding citing the measured number that tripped it; back up the
running config, dry-run a config diff, and merge/replace/rollback config — across the five
core NAPALM platforms below. Optional NetBox lookups (devices + interfaces) confirm
intended state before a change.

NAPALM does not implement every getter on every platform; an unsupported getter
returns a teaching error ("not supported by the `<driver>` driver") rather than
crashing. Secrets are never returned — `get_users` redacts password hashes and
`get_snmp_information` redacts community strings.

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
| Interface traffic + error counters | `get_interfaces_counters` | R | low |
| Interface IP addresses | `get_interfaces_ip` | R | low |
| BGP neighbors (summary / detail) | `get_bgp_neighbors` / `get_bgp_neighbors_detail` | R | low |
| LLDP neighbors (summary / detail) | `get_lldp_neighbors` / `get_lldp_neighbors_detail` | R | low |
| ARP table | `get_arp_table` | R | low |
| MAC address table | `get_mac_address_table` | R | low |
| VLANs | `get_vlans` | R | low |
| Route lookup | `get_route_to` | R | low |
| Hardware environment (fans/temp/power/CPU/mem) | `get_environment` | R | low |
| Optical transceiver levels | `get_optics` | R | low |
| NTP servers / sync stats | `get_ntp_servers` / `get_ntp_stats` | R | low |
| Local users (hashes redacted) | `get_users` | R | low |
| SNMP info (communities redacted) | `get_snmp_information` | R | low |
| Network instances (VRFs) | `get_network_instances` | R | low |
| Aggregated device health | `device_health` | R | low |
| Interface health RCA (down / errors / discards / flaps) | `interface_health_rca` | R | low |
| BGP neighbor RCA (down / shut / reset / route-less) | `bgp_neighbor_rca` | R | low |
| Back up running config | `config_backup` | R | low |
| Diff a candidate (dry-run) | `config_diff` | R | low |
| Merge config + commit | `config_merge` | W | medium |
| Replace full config + commit | `config_replace` | W | **high** |
| Roll back last commit | `config_rollback` | W | medium |
| NetBox list devices | `netbox_list_devices` | R | low |
| NetBox get device | `netbox_get_device` | R | low |
| NetBox device interfaces | `netbox_device_interfaces` | R | low |
| List recorded reversible writes | `undo_list` | R | low |
| Apply a recorded inverse (governed, single-use, dry-run capable) | `undo_apply` | W | medium |

## Security: read-only mode

This tool is meant to be handed to an AI agent, so its safety story is enforced
by the server rather than requested in a prompt:

```bash
export NETWORK_READ_ONLY=1
```

With that set, the **4 write tools are never registered**. An MCP client
lists **28 tools instead of 33** — the writes are not hidden, not
gated behind a flag, and not merely refused when called. They are absent from
the session. A model cannot invoke a tool it was never offered, and cannot be
argued into one.

That distinction is the whole point. A tool that exists but refuses still invites
retry loops and "I'll describe the call instead" behaviour from smaller models,
and it leaves a reviewer trusting a promise. An absent tool is a fact you can
check: connect, list the tools, and see that the writes are not there.

Enforcement is two layers deep, so the switch cannot be sidestepped by changing
entry point:

| Layer | What it does | Covers |
|---|---|---|
| `@governed_tool` harness | refuses every non-read operation outright | MCP, CLI, and in-process callers |
| MCP registration | write tools are removed from `list_tools()` | anything speaking MCP |

Read operations are unaffected, and every call is still audited to
`~/.network-aiops/audit.db`.

> The read/write split is derived from each tool's declared `risk_level`, and a
> test asserts that this never disagrees with the `[READ]`/`[WRITE]` tag in the
> tool's own documentation — so a write can't quietly present itself as a read.

Running a smaller / local model? See
[agent-guardrails.md](skills/network-aiops/references/agent-guardrails.md) — it lists
the guardrails this tool now enforces for you (so you don't spend prompt budget
restating them) and gives a ready-made system prompt for what's left.

## Quick Start

```bash
uv tool install network-aiops
network-aiops init                                  # wizard: device + driver + host + encrypted password
network-aiops doctor
network-aiops device facts -t core-sw1
network-aiops device health -t core-sw1
network-aiops diagnose interface-health -t core-sw1   # worst-first interface RCA
network-aiops diagnose bgp -t core-sw1                # worst-first BGP-neighbor RCA
network-aiops config backup -t core-sw1 -o core-sw1.cfg
```

### Playbook: triage a flaky uplink before touching config

```bash
# 1. Ask the device what's actually wrong — findings are ranked worst-first and
#    each cites the measured value (error count, last-flap seconds, uptime).
network-aiops diagnose interface-health -t core-sw1
network-aiops diagnose bgp -t core-sw1

# 2. If interface-health flags a link admin-up/oper-down with climbing errors and
#    BGP shows the peer on that path recently reset, you have your root cause: a
#    physical-layer fault (cable/optic) resetting the session — not routing.

# 3. Confirm intended state, then remediate with the governed, audited path.
network-aiops device counters -t core-sw1
network-aiops config diff -t core-sw1 -f fix.cfg      # dry-run the change first
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

Secrets are stored **encrypted** in `~/.network-aiops/secrets.enc` (Fernet/AES +
scrypt-derived key; chmod 600) — never in config.yaml or a plaintext `.env`.
Device passwords are keyed by device name; the NetBox token uses the reserved
name `netbox-token`:

```bash
network-aiops init                     # interactive wizard (recommended)
network-aiops secret set core-sw1      # store a device password (hidden prompt)
network-aiops secret set netbox-token  # store the NetBox API token
network-aiops secret list              # names only — values are never printed
network-aiops secret migrate           # import a legacy plaintext .env, then delete it
```

Export `NETWORK_AIOPS_MASTER_PASSWORD` to unlock the store non-interactively (MCP
server / cron). Legacy plaintext env vars (`NETWORK_<TARGET_UPPER>_PASSWORD`,
`NETWORK_NETBOX_TOKEN`) remain a deprecated fallback. An empty device password is
allowed for key-based SSH auth.

## MCP

```jsonc
{
  "command": "network-aiops",
  "args": ["mcp"],
  "env": {
    "NETWORK_AIOPS_CONFIG": "~/.network-aiops/config.yaml",
    "NETWORK_AIOPS_MASTER_PASSWORD": "…"   // unlocks the encrypted secret store
  }
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
- All device text passes through `sanitize()` (output hygiene: control/format-char
  stripping + truncation).
- Device passwords and the NetBox token live only in the encrypted `secrets.enc`
  (chmod 600); tools never return passwords, SNMP community strings, or hashes.

See `skills/network-aiops/SKILL.md` and `SECURITY.md` for details.

## Companion Skills

| If you want… | Use |
|--------------|-----|
| Network device config / facts (Cisco/Arista/Juniper) | **network-aiops** (this) |
| Kubernetes cluster operations | a cluster ops skill |
| Hypervisor VM lifecycle | a hypervisor ops skill |

## Contributing & feature requests

Coverage is intentionally focused. **Need a device or action
that isn't here yet?** Open an issue or pull request at
[github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops/issues)
— contributions, feature requests, and comments are all welcome.

## License

MIT — [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
