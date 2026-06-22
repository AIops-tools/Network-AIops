# network-aiops Setup Guide

## Install

```bash
uv tool install network-aiops
network-aiops doctor
```

`network-aiops` requires Python ≥ 3.11. If `uv` picked an older interpreter:

```bash
uv python install 3.12
uv tool install --python 3.12 --force network-aiops
```

## Configure devices

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
  - name: edge-rtr
    driver: ios
    host: 10.0.0.254
    username: netops
# Optional source-of-truth:
netbox:
  url: https://netbox.example.com
```

### Secrets (never in config.yaml)

Put passwords in `~/.network-aiops/.env` (chmod 600). The env var name is
`NETWORK_<TARGET_UPPER>_PASSWORD` (non-alphanumeric characters become `_`):

```bash
NETWORK_CORE_SW1_PASSWORD=...
NETWORK_EDGE_RTR_PASSWORD=...
NETWORK_NETBOX_TOKEN=...
```

```bash
chmod 700 ~/.network-aiops
chmod 600 ~/.network-aiops/.env
```

### Supported drivers

`ios` (Cisco IOS/IOS-XE), `nxos` / `nxos_ssh` (Cisco Nexus NX-OS), `iosxr`
(Cisco IOS-XR), `eos` (Arista EOS), `junos` (Juniper Junos). Other platforms
(Nokia SR OS / SR Linux, Huawei VRP, …) are reachable via NAPALM community
drivers but are untested here — request official support via a GitHub issue/PR.

## Security

> **Disclaimer**: This is a community-maintained open-source project and is **not affiliated with, endorsed by, or sponsored by Cisco, Arista, Juniper, NetBox Labs, or any network vendor.** Vendor and product names are trademarks of their respective owners. Source is auditable at [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops) under the MIT license.

1. **Source code** — [github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops), MIT.
2. **Config file contents** — `config.yaml` holds only device names, drivers,
   hosts, usernames, and NAPALM `optional_args`. No credentials.
3. **Credentials** — passwords live in `~/.network-aiops/.env`
   (`NETWORK_<TARGET_UPPER>_PASSWORD`) and the NetBox token in
   `NETWORK_NETBOX_TOKEN`; never read, logged, or echoed. Keep the dir 700, `.env` 600.
4. **TLS verification** — NAPALM transports (eAPI/NX-API HTTPS, NETCONF/SSH)
   follow each device's own certificate / SSH host-key configuration; the skill
   does not weaken it.
5. **Prompt-injection protection** — all device-returned text (facts, configs,
   diffs, neighbor data) is run through `sanitize()` (truncation + control-char
   stripping).
6. **Least privilege** — use a device account with only the privilege you need:
   a read-only login for facts/backup, and a config-capable login only for the
   merge/replace/rollback tools.

## Governance harness

Bundled under `network_aiops.governance` — no external dependency. State lives
under `~/.network-aiops/` (override with `NETWORK_AIOPS_HOME`):

- `audit.db` — every tool call (skill, tool, params, status, duration, agent).
- `rules.yaml` — policy deny rules, maintenance windows, risk tiers.
- Token/runaway budget guard (`NETWORK_MAX_TOOL_CALLS`, `NETWORK_MAX_TOOL_SECONDS`,
  `NETWORK_RUNAWAY_MAX`, `NETWORK_RUNAWAY_WINDOW_SEC`).
- Undo store — inverse descriptors for reversible writes (config merge/replace).
- Accountability: set `NETWORK_AUDIT_APPROVED_BY` / `NETWORK_AUDIT_RATIONALE` to
  record who authorized a high-tier operation and why.

## MCP client config

```jsonc
{
  "command": "network-aiops",
  "args": ["mcp"],
  "env": { "NETWORK_AIOPS_CONFIG": "~/.network-aiops/config.yaml" }
}
```

Fallback (no `uv tool install`): `uvx --from network-aiops network-aiops-mcp`.
Prefer the installed entry point — it does not re-resolve PyPI at launch.

## Static analysis

```bash
uvx bandit -r network_aiops/ mcp_server/
```
