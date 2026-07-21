# Live verification status

This document records what has and has not been validated against real network
devices, so the maturity claim is auditable.

## Current status ⚠️ mock-only

`network-aiops` has **not** been validated against live network devices. The
test suite mocks the NAPALM driver throughout. Together with Veeam this is the
largest verification gap in the line — but unlike Veeam it is **self-testable**
without buying hardware:

- **Arista cEOS** or **Juniper vMX/vQFX** container/VM images
- **containerlab** to wire a small multi-vendor lab
- any single real switch/router you own in a lab VRF

## What the mock suite guarantees

Every module imports; the CLI builds; every MCP tool carries the
`@governed_tool` harness marker; config writes record the correct inverse undo
descriptor against a mocked driver; the RCA heuristics
(`interface_health_rca`, `bgp_neighbor_rca`) are unit-tested against synthetic
NAPALM getter output.

It does **not** prove that each vendor driver returns the fields as modelled —
NAPALM getters are normalised, but per-platform gaps are real (some drivers
omit `last_flapped`, counter names differ, BGP structures vary by NOS).

### Credential redaction — what it does and does not promise

`config_backup` and every returned `diff` mask credential VALUES by default
(`network_aiops/ops/redact.py`); `include_secrets=True` returns the verbatim
text, and the CLI's `-o <path>` always writes raw to the operator's file.

**`include_secrets=False` is a REDUCTION of exposure, not a guarantee.** It is
pattern matching over five vendor syntaxes that disagree with each other, so it
will miss things. What is currently covered, and what is known not to be:

Covered by unit tests, against hand-written samples of each syntax — **not yet
against a real device's config**:

| Vendor | Forms matched |
|---|---|
| Cisco IOS/IOS-XE | `enable secret/password`, `username … secret/password`, `snmp-server community`, `crypto isakmp key`, `radius-server`/`tacacs-server key` (typed and untyped), `key-string`, `ntp authentication-key`, BGP `neighbor … password` |
| Cisco NX-OS | `username … password 5`, `snmp-server community … group`, SNMPv3 `auth`/`priv` incl. localised `0x…` digests |
| Cisco IOS-XR | `username … secret`, `password encrypted`, `tacacs-server host … key` |
| Arista EOS | `username … secret sha512`, `enable secret sha512`, `snmp-server community`, `radius-server host … key` |
| Juniper Junos | `encrypted-password`, `snmp community`, `pre-shared-key ascii-text`, `radius-server`/`tacplus-server secret`, `authentication-key`, plus any statement Junos itself tags `## SECRET-DATA` |

**Known gaps — do NOT treat redacted output as cleared for publication:**

- **Multi-line material is invisible to it.** The rules are line-oriented, so an
  embedded PKI key block or `crypto pki certificate chain` body passes through
  whole. This is the largest gap and the one most likely to matter.
- Keywords not in the rule set leak on every vendor except Junos, where
  `## SECRET-DATA` acts as a backstop. Vendors add syntax; this list does not
  update itself.
- Third-party/vendor-specific extensions (wireless controllers, SD-WAN overlays)
  are not modelled at all.
- No live-device corpus has been run through it yet. The false-negative rate on
  a real full config is therefore **unmeasured** — see the checklist below.

## Prerequisites for a live run

A lab device (or containerlab topology) you may reconfigure, reachable over
SSH/NETCONF/eAPI with a least-privilege account. **Never verify config-write
paths against production devices.**

```bash
uv tool install network-aiops
network-aiops init      # encrypted secret store
network-aiops doctor
```

## Checklist

Repeat per driver you care about (`ios`, `nxos`, `iosxr`, `eos`, `junos`).

### 1. Connectivity
- [ ] `network-aiops doctor` → opens a real session to the device.

### 2. Reads return real, well-shaped data
- [ ] Facts / interface listing matches `show interfaces` on the device.
- [ ] `network-aiops diagnose interface-health` → shut an interface
      (admin-up/oper-down or a deliberate error condition) and confirm it is
      flagged with the right counters. Confirm `last_flapped` is populated on
      this driver (some vendors omit it — record if so).
- [ ] `network-aiops diagnose bgp` → drop a BGP session and confirm it is
      flagged not-Established with the correct state/uptime.

### 3. A config write + its undo (the highest-risk path)
- [ ] `config diff <file>` → shows the candidate diff without committing.
- [ ] Commit a trivial, reversible change; confirm the result carries an
      `_undo_id` and an audit row lands in the audit DB.
- [ ] `network-aiops undo apply <id>` → the device returns to the prior config
      (verify with a fresh `config diff` / `show run`).
- [ ] The result's `backup` is a **digest** (`bytes` / `sha256`), NOT the config
      body — grep the result for a known SNMP community and confirm it is absent.
- [ ] The recorded `undo_params` DO contain the byte-exact pre-change config
      (including any banner control characters), i.e. it was not sanitized or
      truncated on the way into `undo.db`.

### 4. Commit-confirm (the lockout guard — needs a real device)
Mock tests prove the plumbing; only a real device proves the timer fires.
- [ ] `config merge <file> --revert-in 60` → result shows
      `commit.mode = "commit-confirm"` and `commit.safetyNet = "commit-confirm"`.
- [ ] Wait out the 60s WITHOUT confirming → the device reverts on its own
      (verify with `config backup` / `show run`). This is the whole point.
- [ ] Repeat, then `network-aiops config confirm` within the window → the change
      is still there after the timer would have expired.
- [ ] **The real test**: stage a change that shuts the management interface with
      `--revert-in 60` from an out-of-band console. The session dies, the device
      restores itself, and the tool becomes reachable again with no undo run.
- [ ] On a driver that does NOT support `revert_in`, confirm the result carries
      `commit.safetyNet = "undo-only"` and the `NO COMMIT-CONFIRM SAFETY NET`
      warning — a silent fallback here would be the dangerous outcome.
- [ ] `confirm_commit` with nothing pending → reports `hadPendingCommit: false`
      rather than erroring.

### 5. Governance records, it does not gate
- [ ] The harness authorizes nothing — there is no read-only, deny-rule, or
      approver gate to test. A `high`-risk op runs and lands an audit row with
      `risk_tier=review`; `NETWORK_AUDIT_APPROVED_BY`, if set, is recorded as an
      optional annotation, never required.

### 6. Credential redaction against a real config
- [ ] `network-aiops config backup -o raw.cfg` then `network-aiops config backup`
      (stdout) on the SAME device; diff the two.
- [ ] Every line that differs is a line that genuinely held a credential — no
      interface, routing or policy line was altered (over-redaction is a defect
      too: it silently changes the config the operator is reading).
- [ ] Grep the redacted text for credential material the rules missed:
      `$1$`, `$5$`, `$6$`, `$9$`, `0x` digests, `BEGIN .* PRIVATE KEY`,
      and the community strings you know the device has. Record what leaked.
- [ ] `redaction.linesRedacted` equals the number of lines that actually changed.
- [ ] Record the platform/version and the false-negative count in this file.
      Until that is done, the honest claim is "reduces exposure", never
      "removes credentials".

### 7. Cleanup
- [ ] Restore the device to its pre-verification config; confirm it is audited.

## Criteria to claim live verification

Every box ticked against at least one real NOS per driver family, with the
platform/version recorded; any field-shape or driver gap fixed (or documented)
and covered by a test; result written up with the date and versions. Until
then this document must continue to say mock-only.
