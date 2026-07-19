"""Flagship signature analyses over NAPALM getter output (pure analysis).

Network-AIops was born read-heavy (facts + counters + config ops); these two
analyses bring it to parity with the rest of the line, whose differentiator is a
*transparent* RCA: every finding is reported with the measured number that
tripped it, so an operator sees **why** an interface or peer was flagged — never
a black-box verdict.

  1. ``interface_health_findings`` — flag interfaces that are admin-up but
     oper-down, carrying high error / discard counters, or that flapped
     recently, each citing the measured value and a concrete action.
  2. ``bgp_neighbor_findings`` — flag BGP neighbors that are not up (down vs
     administratively shut), that recently reset (low uptime), or that are up
     yet learning zero prefixes.

Both are pure functions (no I/O): pass them the already-normalized rows from
``ops.facts.get_interfaces`` / ``ops.inventory.get_interfaces_counters`` /
``ops.facts.get_bgp_neighbors`` and they return the analysis. The MCP / CLI
layers do the device collection; keeping the heuristics pure makes them
trivially unit-testable without a live device.
"""

from __future__ import annotations

from typing import Any

# Thresholds that flip a signal on. Each is surfaced in the finding text next to
# the measured value so the ranking is auditable, not opaque.
IFACE_ERRORS_WARN = 100  # cumulative rx+tx errors since boot
IFACE_DISCARDS_WARN = 100  # cumulative rx+tx discards since boot
FLAP_RECENT_SEC = 300.0  # link transition within the last 5 minutes
BGP_YOUNG_SEC = 300  # session up for < 5 minutes → recently reset

# Severity ordering used to rank findings most-urgent first.
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _num(value: Any) -> float:
    """Coerce a counter to float, treating missing / non-numeric as 0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _within(value: Any, ceiling: float) -> bool:
    """True when ``value`` is a real number in ``[0, ceiling)`` (else unknown)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= v < ceiling


def _finding(
    severity: str, entity: str, signal: str, detail: str, cause: str, action: str
) -> dict:
    """Build one cited finding (immutable dict — callers never mutate it)."""
    return {
        "severity": severity,
        "entity": entity,
        "signal": signal,
        "detail": detail,
        "cause": cause,
        "action": action,
    }


def _rank(findings: list[dict]) -> list[dict]:
    """Return findings most-urgent first, each carrying its explicit 1-based rank.

    The priority is stated in the payload rather than left implicit in list
    order: a consumer — notably a smaller local model summarising the result —
    should never have to infer urgency from position. Returns new dicts; the
    inputs are not mutated.
    """
    ordered = sorted(findings, key=lambda f: _SEVERITY_RANK.get(f["severity"], 9))
    return [{**finding, "rank": i} for i, finding in enumerate(ordered, 1)]


def _interface_row_findings(iface: dict, counters_by_name: dict) -> list[dict]:
    """All findings for one interface, citing the measured value each time."""
    name = str(iface.get("interface") or "?")
    out: list[dict] = []
    if bool(iface.get("is_enabled")) and not bool(iface.get("is_up")):
        out.append(_finding(
            "critical", name, "interface down",
            "admin-enabled (is_enabled=True) but link is down (is_up=False)",
            "Physical-layer fault: unseated cable/SFP, peer port down, or a "
            "speed/duplex mismatch.",
            "Check the cable/optic and the peer port; confirm speed/duplex.",
        ))
    c = counters_by_name.get(name) or {}
    errs = _num(c.get("rx_errors")) + _num(c.get("tx_errors"))
    if errs >= IFACE_ERRORS_WARN:
        out.append(_finding(
            "warning", name, "interface errors",
            f"rx_errors+tx_errors = {int(errs)} >= {IFACE_ERRORS_WARN} (since boot)",
            "Frame/CRC errors point to a bad cable, a dirty/failing optic, or a "
            "duplex mismatch.",
            "Inspect the cable/optic, clear counters, and watch if errors climb.",
        ))
    disc = _num(c.get("rx_discards")) + _num(c.get("tx_discards"))
    if disc >= IFACE_DISCARDS_WARN:
        out.append(_finding(
            "warning", name, "interface discards",
            f"rx_discards+tx_discards = {int(disc)} >= {IFACE_DISCARDS_WARN} (since boot)",
            "Discards indicate congestion / buffer exhaustion, not a physical fault.",
            "Check link utilization and QoS; the port may be oversubscribed.",
        ))
    flapped = iface.get("last_flapped")
    if _within(flapped, FLAP_RECENT_SEC):
        out.append(_finding(
            "warning", name, "interface flapped",
            f"last_flapped = {flapped}s ago (< {int(FLAP_RECENT_SEC)}s)",
            "A recent link transition suggests an unstable optic, cable, or peer.",
            "Correlate with logs/optics; a flap resets protocols riding the link.",
        ))
    return out


def interface_health_findings(interfaces: list[dict], counters: list[dict]) -> dict:
    """[ANALYSIS] Flag down / erroring / discarding / flapping interfaces.

    Args:
        interfaces: rows from ``ops.facts.get_interfaces`` (``interface``,
            ``is_up``, ``is_enabled``, ``last_flapped``).
        counters: rows from ``ops.inventory.get_interfaces_counters`` (joined by
            ``interface`` name for rx/tx error and discard counts).

    Returns the worst-first ``findings`` list and the count analyzed.
    """
    by_name = {c.get("interface"): c for c in counters}
    findings: list[dict] = []
    for iface in interfaces:
        findings.extend(_interface_row_findings(iface, by_name))
    return {"findings": _rank(findings), "interfacesAnalyzed": len(interfaces)}


def _bgp_peer_findings(peer: dict) -> list[dict]:
    """All findings for one BGP neighbor, citing the session state / uptime."""
    name = str(peer.get("neighbor") or "?")
    label = f"{name} (vrf {peer.get('vrf')}, AS {peer.get('remote_as')})"
    up = bool(peer.get("is_up"))
    enabled = bool(peer.get("is_enabled"))
    if not up and enabled:
        return [_finding(
            "critical", name, "BGP session down",
            f"{label}: is_up=False, is_enabled=True",
            "Peer unreachable, or blocked by an ACL / MD5-auth mismatch / missing "
            "route to the peer.",
            "Verify reachability to the peer, the inbound ACL, and MD5/password.",
        )]
    if not up and not enabled:
        return [_finding(
            "info", name, "BGP session shut",
            f"{label}: is_up=False, is_enabled=False (administratively down)",
            "The neighbor is configured but administratively shut.",
            "If the peering is expected, no-shutdown it; otherwise this is benign.",
        )]
    if _within(peer.get("uptime"), BGP_YOUNG_SEC):
        return [_finding(
            "warning", name, "BGP session recently reset",
            f"{label}: up for only {int(_num(peer.get('uptime')))}s (< {BGP_YOUNG_SEC}s)",
            "A short uptime means the session recently reset — likely flapping.",
            "Check peer/link stability and logs; a flap churns the routing table.",
        )]
    if peer.get("received_prefixes") == 0:
        return [_finding(
            "info", name, "BGP no prefixes received",
            f"{label}: session up but received_prefixes=0",
            "The peer is up but advertising no routes.",
            "Confirm the peer's outbound policy / prefix-lists if routes are expected.",
        )]
    return []


def bgp_neighbor_findings(neighbors: list[dict]) -> dict:
    """[ANALYSIS] Flag BGP neighbors that are down, shut, flapping, or route-less.

    Args:
        neighbors: rows from ``ops.facts.get_bgp_neighbors`` (``vrf``,
            ``neighbor``, ``remote_as``, ``is_up``, ``is_enabled``, ``uptime``,
            ``received_prefixes``).

    Returns the worst-first ``findings`` list, the count analyzed, and the number
    of enabled-but-down sessions.
    """
    findings: list[dict] = []
    for peer in neighbors:
        findings.extend(_bgp_peer_findings(peer))
    down = sum(1 for p in neighbors if p.get("is_enabled") and not p.get("is_up"))
    return {
        "findings": _rank(findings),
        "neighborsAnalyzed": len(neighbors),
        "sessionsDown": down,
    }
