# Changelog

## v0.12.0 — 2026-09-12

### Added
- **Installable as a Claude Code plugin.** `.claude-plugin/plugin.json` plus a
  root `.mcp.json` make this repo a plugin, so `/plugin install network-aiops@aiops-tools`
  delivers the skill and registers the MCP server in one step. The server is
  pinned to the exact package version the manifest declares, so an audit row
  stays traceable to the code that produced it. Nothing about the tool itself
  changed — the CLI and the standalone MCP server work exactly as before.
- **Installable from ClawHub as an OpenClaw bundle plugin** (`@aiops-tools/network-aiops`): one install delivers the skill *and* its MCP
  server, pinned to this exact release. `clawhub.ai/plugins`.

### Fixed
- **The skill was invisible to the model in OpenClaw.** Its metadata
  declared `requires.config` (OpenClaw reads that as config *keys*, not file
  paths, so it can never be satisfied), `requires.env` and `requires.bins`
  naming our own CLI — which a plugin user never has on PATH — plus a
  `primaryEnv` that turned a config path into an API-key prompt. Measured on
  OpenClaw 2026.6.35: `Visible to model: no`. It now requires
  `anyBins: [network-aiops, uvx]` — either one suffices — with every variable kept
  in `optional.env` (still declared, no longer a load gate), which the same
  command reports as `Visible to model: yes`.
## v0.11.0 — 2026-08-10

### Fixed
- **An undetermined outcome no longer exits as a plain failure.** A write whose response was lost carries *both* `error` and `outcomeUnknown`, and the harness deliberately judges unknown first when writing the audit row — the change may have taken effect, so a blind retry could apply it twice. The CLI guard judged `error` first, so the audit said "may have taken effect" while the exit status told a script it had not happened. The two layers now agree (exit 2, not 1), and a test pins the ordering so it cannot silently flip back.
- **The CLI reported a refused or failed governed write as a success.** 1 write call site (`undo apply`) printed the governed twin's payload and exited **0** whatever it said — and `@tool_errors` flattens every refusal, guard rejection and upstream failure into `{"error": ...}` rather than raising, so nothing downstream of a `&&` chain or a CI step could tell a blocked write from a landed one. The dry-run path already exited non-zero, which made the asymmetry worse: the preview was stricter than the write it previews. Results now route through a `checked()` helper — exit 1 on an error payload, exit 2 on an undetermined outcome, unchanged on success. This defect class had been fixed repo-by-repo several times and kept coming back; an audit across the whole line found it live in **18 of the 24 tools at once (87 call sites)**, so each tool now carries an invariant test that fails if any future CLI command prints a governed result without checking it.

## v0.10.0 — 2026-08-03

### Fixed
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.9.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.
- Docs: records the NetBox half as live-verified against NetBox 4.6.6. The NAPALM device half still requires a real device or a vendor account for cEOS. **No code change.**


## v0.8.0 — 2026-07-21

### Changed
- CLI `--dry-run` previews for the remaining write commands now route through the governed twin (run the guards, land an audit row) instead of a static unaudited banner.

See RELEASE_NOTES.md for detail.


## v0.7.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.6.0 — 2026-07-20

### Fixed
- **Commit-confirm.** `config_merge` and `config_replace` now commit with `revert_in` (default 300s) and there is a new `confirm_commit` tool.
- **The full running config is no longer returned to the caller.** `config_merge` / `config_replace` used to hand back the entire backup — credential hashes, SNMP communities, PSKs, RADIUS keys — straight into the agent transcript.
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.9.0 — 2026-08-02

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
