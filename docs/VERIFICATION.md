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

### 4. Governance actually gates
- [ ] With no `rules.yaml`, a `high`-risk op is refused unless
      `NETWORK_AUDIT_APPROVED_BY` names an approver (secure-by-default).

### 5. Cleanup
- [ ] Restore the device to its pre-verification config; confirm it is audited.

## Criteria to claim live verification

Every box ticked against at least one real NOS per driver family, with the
platform/version recorded; any field-shape or driver gap fixed (or documented)
and covered by a test; result written up with the date and versions. Until
then this document must continue to say mock-only.
