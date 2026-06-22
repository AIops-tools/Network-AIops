# network-aiops Capabilities

13 MCP tools (10 read / 3 write). Every tool is wrapped with `@governed_tool`
(audit + policy + budget + risk-tier; undo where a clean inverse exists). Returns
are high-signal summaries — config blobs are sanitized and size-bounded.

## Read tools

| Tool | Returns | Risk | Typical response tokens |
|------|---------|:----:|:-----------------------:|
| `device_facts` | hostname, vendor, model, os_version, serial, uptime, interface list | low | ~80–300 |
| `get_interfaces` | per-interface up/enabled/speed/description/mac | low | ~60–800 |
| `get_interfaces_ip` | per-interface IPv4/IPv6 + prefix length | low | ~40–400 |
| `get_bgp_neighbors` | per-VRF peer, remote AS, up, prefix counts | low | ~60–600 |
| `get_lldp_neighbors` | local port, remote host, remote port | low | ~40–400 |
| `get_arp_table` | interface, IP, MAC, age | low | ~50–700 |
| `config_backup` | running config (sanitized, size-bounded) | low | ~500–8000 |
| `config_diff` | candidate diff (dry-run, never committed) | low | ~30–1500 |
| `netbox_list_devices` | name, role, site, status, primary IP | low | ~40–500 |
| `netbox_get_device` | + device_type, serial | low | ~80 |

## Write tools

| Tool | Effect | Risk | Undo |
|------|--------|:----:|------|
| `config_merge` | merge snippet + commit | medium | `config_replace` back to captured running config |
| `config_replace` | replace full config + commit | **high** | `config_replace` back to captured running config |
| `config_rollback` | revert last commit | medium | none (already a revert) |

## Per-driver support notes

| Getter / op | ios | nxos / nxos_ssh | iosxr | eos | junos |
|-------------|:---:|:---------------:|:-----:|:---:|:-----:|
| `get_facts` / `get_interfaces` / `get_interfaces_ip` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `get_bgp_neighbors` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `get_lldp_neighbors` / `get_arp_table` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `get_config` (backup) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `load_merge_candidate` + `compare_config` (diff/merge) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `load_replace_candidate` (replace) | ✓ | varies | ✓ | ✓ | ✓ |
| `rollback` | ✓ (archive) | varies | ✓ | ✓ | ✓ |

A getter that a given driver does not implement raises `NotImplementedError`,
which the ops layer turns into a teaching `NetworkApiError` ("not supported by
the `<driver>` driver").

## Token-budget notes

- `config_backup` can be large; prefer `config_diff` to preview a change instead
  of re-fetching the whole config repeatedly.
- The runaway guard trips on tight poll loops — wait between repeated reads.

## Design notes / NAPALM assumptions

- NAPALM connections are short-lived: each tool opens a driver, runs its
  getters/config calls, and closes it. Nothing is cached across calls.
- Passwords come from `~/.network-aiops/.env` (`NETWORK_<TARGET_UPPER>_PASSWORD`);
  enable/secret and transport go in `optional_args` and are passed verbatim to
  NAPALM. The skill never logs or echoes the credential.
- Connection / command / driver errors are translated centrally at the connection
  layer into a teaching `NetworkApiError`, so agents see actionable messages.
- Only the five core drivers are validated here; community drivers are untested.
