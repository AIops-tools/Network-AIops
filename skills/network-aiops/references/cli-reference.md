# network-aiops CLI Reference

All commands accept `-t/--target <name>` to select a configured device. When
omitted, the first device in `~/.network-aiops/config.yaml` is used.

## Device facts (read-only)

```bash
network-aiops device facts [-t <device>]        # hostname, vendor, model, OS, serial, uptime
network-aiops device interfaces [-t <device>]   # up/down, enabled, speed, description
network-aiops device bgp [-t <device>]          # BGP neighbors per VRF
network-aiops device lldp [-t <device>]         # LLDP neighbors
network-aiops device arp [-t <device>]          # ARP table
```

## Configuration

```bash
network-aiops config backup [-t <device>] [-o <file>]      # running config (save with -o)
network-aiops config diff <file> [-t <device>] [--replace] # DRY-RUN: show the diff only
network-aiops config merge <file> [-t <device>] [--dry-run]    # commit; double confirm
network-aiops config replace <file> [-t <device>] [--dry-run]  # HIGH RISK; double confirm
network-aiops config rollback [-t <device>] [--dry-run]        # revert last commit; double confirm
```

- `config diff` stages a candidate, runs `compare_config()`, and discards it —
  nothing is committed. `--replace` diffs as a full-config replacement.
- `--dry-run` on `merge` / `replace` prints the same diff without committing.
- `merge` / `replace` capture the pre-change running config for the undo store.

## NetBox (optional source-of-truth)

```bash
network-aiops netbox list [--name <q>] [--limit N]   # name, role, site, status, primary IP
network-aiops netbox get <name>                      # single device by exact name
```

Requires a `netbox:` block in config and `NETWORK_NETBOX_TOKEN` in `.env`.

## Diagnostics & MCP

```bash
network-aiops doctor [--skip-auth]   # check config + per-device password env vars + reachability
network-aiops mcp                    # start the MCP server over stdio
```

## Flags summary

| Flag | Meaning |
|------|---------|
| `-t, --target` | Device name from `~/.network-aiops/config.yaml` |
| `-o, --output` | Write `config backup` output to a file |
| `--replace` | Diff/treat the config file as a full replacement (`config diff`) |
| `--dry-run` | Preview a destructive config op as a diff without committing |
| `--name` | NetBox name filter (`netbox list`) |
| `--limit` | NetBox page size (`netbox list`) |
| `--skip-auth` | Skip the connectivity check in `doctor` |
