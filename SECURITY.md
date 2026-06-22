# Security Policy

## Disclaimer

This is a community-maintained open-source project and is **not affiliated with,
endorsed by, or sponsored by Cisco, Arista, Juniper, NetBox Labs, or any network
vendor.** Vendor and product names are trademarks of their respective owners.
Source code is publicly auditable at
[github.com/AIops-tools/Network-AIops](https://github.com/AIops-tools/Network-AIops)
under the MIT license.

## Reporting Vulnerabilities

Report security issues privately to **zhouwei008@gmail.com** or via a GitHub
private security advisory on the repository. Please do not open public issues for
undisclosed vulnerabilities.

## Security Design

### Credential Management

Device passwords are read from `~/.network-aiops/.env` as
`NETWORK_<TARGET_UPPER>_PASSWORD` (one per device); enable/secret and transport
options go in the device's `optional_args` and are passed verbatim to NAPALM. The
optional NetBox token is read from `NETWORK_NETBOX_TOKEN`. `config.yaml` holds
only device names, drivers, hosts, usernames, and `optional_args` — never
secrets. The state directory `~/.network-aiops` should be owner-only
(`chmod 700`) and `.env` `chmod 600`; the skill warns if the directory is more
permissive. Credentials are never read into results, logged, or echoed.

### Destructive Operation Safety

Config write operations (merge, replace, rollback) all pass through the bundled
`@governed_tool` decorator: policy pre-check, token / runaway budget guard,
graduated-autonomy risk-tier gate, and audit logging. The CLI layer additionally
requires double confirmation and supports `--dry-run` (which prints the diff
without committing) for `config merge`, `config replace`, and `config rollback`.
`config_merge` and `config_replace` capture the pre-change running config and
record an inverse `config_replace`-to-backup undo descriptor; `config_rollback`
declares no undo; `config_replace` is tagged `risk_level=high`. `config_diff` is a
pure dry-run (stage candidate → compare → discard).

### Least Privilege

Use a device account with only the privilege you need — a read-only login for
facts/backup, and a config-capable login only for the merge/replace/rollback
tools. The optional NetBox token should be read-only.

### Webhooks / Outbound Network

None. The skill makes no outbound network calls beyond the configured device
sessions (NAPALM) and the optional NetBox API. There are no background services
or post-install scripts.

### TLS Verification

NAPALM driver transports (eAPI / NX-API over HTTPS, NETCONF / SSH) follow each
device's own certificate and SSH host-key configuration. The skill does not
weaken transport security.

### Prompt Injection Protection

All text returned from a device (facts, configs, diffs, interface descriptions,
neighbor data) and from NetBox is run through `sanitize()` — truncation plus
C0/C1 control-character stripping — before reaching the agent.

### Transitive Dependencies

`napalm` (device drivers), `pynetbox` (optional source-of-truth), `typer`/`rich`
(CLI), `pyyaml`/`python-dotenv` (config), and the MCP SDK. No external
skill-family dependency — the governance harness is vendored under
`network_aiops.governance`.

## Static Analysis

```bash
uvx bandit -r network_aiops/ mcp_server/
```

## Supported Versions

The latest released version (currently 0.1.0, preview) receives security fixes.
