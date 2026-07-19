# Changelog

## Unreleased

### Added
- **Diagnostics / RCA (read-only, `risk_level=low`)**: two flagship analyses that
  rank findings worst-first, each citing the measured value that tripped it —
  `interface_health_rca` (admin-up/oper-down links, high error/discard counters,
  recent flaps via `last_flapped`) and `bgp_neighbor_rca` (neighbors down vs
  administratively shut, recently reset via low uptime, or up-but-route-less).
  New CLI sub-app `network-aiops diagnose interface-health|bgp`. Tool count **28 → 30**.
  Pure heuristics live in `network_aiops.ops.diagnostics`; `get_interfaces` and
  `get_bgp_neighbors` now also surface `last_flapped` / `uptime`.

## v0.4.0 — 2026-07-17

### Added
- **Undo executor**: `undo list` / `undo apply <id>` (CLI + MCP) — apply a recorded replayable inverse; the dispatched inverse is re-gated by its own risk tier; single-use, dry-run, double-confirm, both wrapper + inverse audited.

## v0.3.1 — 2026-07-16

### Fixed
- **`secrets.enc` now follows `NETWORK_AIOPS_HOME`** (secretstore hardcoded the real
  home directory; config/audit/undo already relocated — found in live verification).
- **Audit fidelity**: failures sanitized into `{"error": ...}` results by the MCP error
  layer are now audited as `status=error` (they previously read as `ok`, hiding failed
  attempts from exception reports), and no undo is recorded for a call that failed.

### Tests
- `doctor` and the `init` wizard are now fully covered (previously ~10–20%); plus a
  regression test for the sanitized-failure audit status.

## v0.3.0 — 2026-07-13

Security-hardening release from a line-wide code review.

### Changed (behavior)
- **Secure by default**: with no `rules.yaml`, high/critical operations now require a
  named approver (`NETWORK_AUDIT_APPROVED_BY`). A fresh install no longer allows
  destructive writes unattended; `init` seeds a starter `rules.yaml` you can edit,
  and an operator-authored rules file is honoured as-is.
- `__version__` is now single-sourced from package metadata (the previous release
  self-reported a stale version string).
- Sanitize docs no longer overstate scope: it strips control/format characters and
  truncates; semantic prompt-injection resistance must come from the consuming agent.

### Fixed
- NAPALM drivers get a default 60s timeout via `optional_args` (user values win).
- First dedicated ops-layer test suite (driver call plumbing, config merge/replace/rollback, NetBox).

### Tests
- Governance persistence is now tested against REAL `audit.db`/`undo.db` files
  (write → audit row + inverse undo row with captured prior state).
- The CLI confirmed-write path (dry-run / double-confirm / governed execution) is
  covered end-to-end.
- `pytest-cov` added to the dev dependencies.

## v0.2.1

- Fix: `NETWORK_AIOPS_HOME` now also relocates `config.yaml` (was hardcoded to `~/.network-aiops`).
- Fix: **CLI writes are now audited + undo-recorded** via the governance path — previously only the MCP tools recorded audit/undo; CLI `manage`/`remediate`/etc. writes now go through the same `@governed_tool` layer (they keep their dry-run + double-confirm). CLI write output is now the governed JSON result. No API/tool changes.


All notable changes to **network-aiops** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-06-27

Encrypted credentials, a friendly onboarding wizard, and MCP tools expanded from
**13 → 28**.

### Added
- **Encrypted credential store** — both per-device login passwords **and** the
  NetBox API token now live in `~/.network-aiops/secrets.enc` (Fernet/AES + HMAC,
  scrypt-derived master password). No plaintext on disk; `chmod 600`. Device
  passwords are keyed by device name; the NetBox token uses the reserved name
  `netbox-token`.
- **Onboarding wizard** — `network-aiops init` collects device name, NAPALM driver
  (validated against the supported set), host, username, optional args, and a hidden
  password (stored encrypted); optionally a NetBox URL + token.
- **Secret management** — `network-aiops secret set/list/rm/migrate/rotate-password`
  (`migrate` imports legacy `NETWORK_<TARGET>_PASSWORD` and `NETWORK_NETBOX_TOKEN`).
- **NAPALM read getters** — BGP neighbors detail, LLDP neighbors detail, interface
  counters/IPs, MAC address table, VLANs, `get_route_to`, environment
  (fans/temp/power/CPU/mem), optics, NTP servers/stats, users, SNMP info, network
  instances (VRFs), and an aggregated `device_health`.
- **NetBox enrichment** — `netbox_device_interfaces` (source-of-truth interface list).

### Changed
- `config.py` resolves device passwords and the NetBox token from the encrypted
  store first, then legacy env vars (with a deprecation warning). An empty device
  password remains valid (key-based SSH auth).
- `doctor` reports encrypted-store presence/permissions and nudges to `init`.
- Added the `cryptography` dependency.

### Security
- Secrets are redacted in output: `get_users` reduces password hashes to a boolean,
  `get_snmp_information` reduces community strings to a count. No tool returns
  passwords or tokens. Master password via `NETWORK_AIOPS_MASTER_PASSWORD`.

### Notes
- NAPALM does not implement every getter on every platform; unsupported getters
  return a teaching "not supported by the '<driver>' driver" error instead of
  crashing. Still preview/mock-validated against a fake driver.

## [0.1.0] — 2026-06-22

Initial preview release: facts, config merge/replace/rollback, NetBox lookups
(13 MCP tools), with the vendored governance harness.

[0.2.0]: https://github.com/AIops-tools/Network-AIops/releases/tag/v0.2.0
[0.1.0]: https://github.com/AIops-tools/Network-AIops/releases/tag/v0.1.0
