"""``config_backup`` used to hand the whole running config to the caller.

A previous round stopped ``config_merge``/``config_replace`` returning the
config body — they return a size + SHA-256 digest and keep the raw text in
undo.db. ``config_backup`` was not changed, and it is the tool whose entire
contract IS returning that text: credential hashes, SNMP communities, IKE
pre-shared keys, RADIUS/TACACS keys, straight into the caller's transcript.

So the fix is not "withhold it" — that would delete the tool. It is: mask the
credential VALUES by default, keep every other line byte-for-byte, report how
many lines changed, and offer ``include_secrets=True`` for the cases that
genuinely need the real thing.

These tests pin all four halves of that contract, plus the deliberate asymmetry
in the CLI: ``-o <path>`` writes RAW. A file the operator named is not a model's
context window, and collapsing the two would make the tool useless for taking
an actual backup.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from network_aiops.ops import config_ops
from network_aiops.ops.redact import PLACEHOLDER, redact_config

pytestmark = pytest.mark.unit


# One line per vendor syntax the tool declares support for, each paired with the
# substring that must not survive. Cisco IOS / NX-OS / IOS-XR, Arista EOS and
# Juniper Junos spell every one of these differently; a rule set written against
# one of them is a rule set that leaks on the other four.
_SECRET_LINES = [
    # Cisco IOS / IOS-XE
    ("ios-enable-secret", "enable secret 5 $1$mERr$Xm2Q1FZ8VqPn", "$1$mERr$Xm2Q1FZ8VqPn"),
    ("ios-enable-password", "enable password 7 08701E1D5D4C53", "08701E1D5D4C53"),
    ("ios-username", "username ops privilege 15 secret 5 $1$ab$cd", "$1$ab$cd"),
    ("ios-snmp-community", "snmp-server community pubL1cR0 RO", "pubL1cR0"),
    ("ios-isakmp-psk", "crypto isakmp key MySharedKey123 address 10.0.0.1", "MySharedKey123"),
    ("ios-radius-key", "radius-server key 7 121A0C041104", "121A0C041104"),
    ("ios-tacacs-key-plain", "tacacs-server key MyTacacsKey", "MyTacacsKey"),
    ("ios-tacacs-host-key", "tacacs-server host 10.1.1.1 port 49 key 7 04480E05", "04480E05"),
    ("ios-keychain", " key-string 7 060506324F41", "060506324F41"),
    ("ios-ntp-key", "ntp authentication-key 1 md5 05080F1C2243 7", "05080F1C2243"),
    ("ios-bgp-password", " neighbor 10.0.0.1 password 7 060506324F41", "060506324F41"),
    # Cisco NX-OS
    ("nxos-username", "username admin password 5 $5$Kj2n$abc role network-admin", "$5$Kj2n$abc"),
    ("nxos-snmpv3-auth", "snmp-server user a auth md5 0x1a2b priv 0x3c4d localizedkey", "0x1a2b"),
    ("nxos-snmpv3-priv", "snmp-server user a auth md5 0x1a2b priv 0x3c4d localizedkey", "0x3c4d"),
    ("nxos-community", "snmp-server community roComm group network-operator", "roComm"),
    # Cisco IOS-XR
    ("iosxr-username", "username lab secret 5 $1$xyz$abc", "$1$xyz$abc"),
    ("iosxr-password-encrypted", " password encrypted 060506324F41", "060506324F41"),
    # Arista EOS
    ("eos-username", "username admin role network-admin secret sha512 $6$Sa1t$H", "$6$Sa1t$H"),
    ("eos-enable", "enable secret sha512 $6$aBc$dEf", "$6$aBc$dEf"),
    ("eos-community", "snmp-server community eosComm ro", "eosComm"),
    ("eos-radius", "radius-server host 10.2.2.2 key 7 020A0F485D", "020A0F485D"),
    # Juniper Junos — set style
    ("junos-root-auth", 'set system root-authentication encrypted-password "$6$r$abc"', "$6$r$abc"),
    ("junos-community", "set snmp community junosComm authorization read-only", "junosComm"),
    ("junos-ike-psk", 'set security ike policy P pre-shared-key ascii-text "$9$aB"', "$9$aB"),
    ("junos-radius", 'set system radius-server 10.3.3.3 secret "$9$secretval"', "$9$secretval"),
    ("junos-bgp-key", 'set protocols bgp group G authentication-key "$9$bgpkey"', "$9$bgpkey"),
    # Juniper Junos — curly-brace style, incl. the vendor's own SECRET-DATA
    # marker, which is the only signal that catches a keyword we do not know.
    ("junos-secret-data", '    some-future-key "$9$unknown"; ## SECRET-DATA', "$9$unknown"),
]

# Config that carries no credential and MUST come back byte-for-byte. A
# redactor that mangles interface or routing config has destroyed the tool it
# was meant to protect.
_ORDINARY_LINES = [
    "hostname core-sw1",
    "interface GigabitEthernet0/1",
    " description Uplink to core-sw2",
    " ip address 10.0.0.1 255.255.255.0",
    " switchport mode trunk",
    " switchport trunk allowed vlan 10,20,30",
    "router bgp 65001",
    " neighbor 10.0.0.2 remote-as 65002",
    " network 10.0.0.0 mask 255.255.255.0",
    "ip route 0.0.0.0 0.0.0.0 10.0.0.254",
    "aaa authentication login default group radius local",
    "ip radius source-interface Loopback0",
    "service password-encryption",
    "key chain BGP-KEYS",
    "crypto key generate rsa modulus 2048",
    "logging host 10.9.9.9",
    "ntp server 10.0.0.99",
    "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24",
    "set system services ssh root-login deny",
    "aaa group server tacacs+ TACGROUP",
]


# ── the redactor itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line,secret", [(line, secret) for _, line, secret in _SECRET_LINES],
    ids=[name for name, _, _ in _SECRET_LINES],
)
def test_a_credential_value_does_not_survive_redaction(line, secret):
    redacted, count = redact_config(line)
    assert secret not in redacted, f"credential survived: {redacted}"
    assert PLACEHOLDER in redacted
    assert count == 1


@pytest.mark.parametrize("line", _ORDINARY_LINES)
def test_ordinary_config_is_returned_untouched(line):
    """Exactness. Over-redaction is not the safe direction here — it is a
    different way of failing to return the config the caller asked for."""
    redacted, count = redact_config(line)
    assert redacted == line
    assert count == 0


def test_the_line_keeps_its_shape_so_the_config_stays_readable():
    """The VALUE goes, not the line. 'which accounts exist' is usually the
    actual question, and it survives; the hash that answers nothing does not."""
    redacted, _ = redact_config("username ops privilege 15 secret 5 $1$ab$cd")
    assert redacted == f"username ops privilege 15 secret 5 {PLACEHOLDER}"


def test_both_secrets_on_one_line_are_masked():
    """A line can carry two. Masking the first and stopping is a silent leak."""
    line = "snmp-server user a auth md5 0xAAAA priv 0xBBBB localizedkey"
    redacted, count = redact_config(line)
    assert "0xAAAA" not in redacted and "0xBBBB" not in redacted
    assert count == 1, "the count is lines changed, not values masked"


def test_the_count_is_the_number_of_lines_changed():
    text = "\n".join(["hostname sw1", "enable secret 5 $1$a$b", "interface Et1",
                      "snmp-server community pub RO"])
    redacted, count = redact_config(text)
    assert count == 2
    assert "hostname sw1" in redacted and "interface Et1" in redacted


def test_line_structure_and_trailing_newline_survive():
    text = "hostname sw1\nenable secret 5 $1$a$b\n"
    redacted, _ = redact_config(text)
    assert redacted.endswith("\n")
    assert len(redacted.splitlines()) == 2


def test_empty_input_is_not_an_error():
    assert redact_config("") == ("", 0)
    assert redact_config(None) == ("", 0)


# ── config_backup: redacted by default, opt-in to raw ───────────────────────


_CONFIG_WITH_SECRET = (
    "hostname core-sw1\n"
    "interface Ethernet1\n"
    " description Uplink to core\n"
    "snmp-server community s3cr3tCommunity RO\n"
    "enable secret 5 $1$mERr$Xm2Q1FZ8VqPn\n"
)


@pytest.fixture
def secretful_device(fake_driver_cls, monkeypatch):
    """A device whose running config actually contains credentials."""
    monkeypatch.setattr(
        fake_driver_cls, "get_config",
        lambda self, retrieve="running": {"running": _CONFIG_WITH_SECRET},
    )
    return fake_driver_cls


def test_backup_masks_credentials_by_default(secretful_device, eos_target):
    result = config_ops.config_backup(eos_target)
    assert "s3cr3tCommunity" not in result["config"]
    assert "$1$mERr$Xm2Q1FZ8VqPn" not in result["config"]


def test_backup_leaves_the_rest_of_the_config_alone(secretful_device, eos_target):
    result = config_ops.config_backup(eos_target)
    assert "hostname core-sw1" in result["config"]
    assert "interface Ethernet1" in result["config"]
    assert " description Uplink to core" in result["config"]


def test_backup_reports_that_it_redacted_and_how_much(secretful_device, eos_target):
    """A silent transformation is the defect. The caller must be able to tell
    that what it is reading is not what the device said."""
    redaction = config_ops.config_backup(eos_target)["redaction"]
    assert redaction["applied"] is True
    assert redaction["linesRedacted"] == 2
    assert "include_secrets" in redaction["note"]


def test_backup_with_include_secrets_returns_the_verbatim_config(
    secretful_device, eos_target
):
    """The capability is not lost, only moved behind an explicit ask."""
    result = config_ops.config_backup(eos_target, include_secrets=True)
    assert result["config"] == _CONFIG_WITH_SECRET
    assert result["redaction"]["applied"] is False
    assert result["redaction"]["linesRedacted"] == 0
    assert "NOT REDACTED" in result["redaction"]["note"]


def test_the_redaction_block_is_present_even_when_nothing_matched(
    fake_driver_cls, eos_target
):
    """Key always present, per the line's missing-vs-empty rule. 'applied with
    0 hits' and 'not applied' are different facts and must stay distinguishable."""
    redaction = config_ops.config_backup(eos_target)["redaction"]
    assert redaction["applied"] is True
    assert redaction["linesRedacted"] == 0
    assert "not proof" in redaction["note"], "must not claim the text is clean"


# ── the same treatment for diffs ────────────────────────────────────────────
#
# A diff that ADDS 'snmp-server community X' contains X just as surely as the
# config does; one that removes a line quotes the credential the device had.


@pytest.fixture
def secretful_diff(fake_driver_cls, monkeypatch):
    monkeypatch.setattr(
        fake_driver_cls, "compare_config",
        lambda self: "+snmp-server community n3wCommunity RO\n-ntp server 10.0.0.99",
    )
    return fake_driver_cls


def test_config_diff_masks_credentials_by_default(secretful_diff, eos_target):
    result = config_ops.config_diff(eos_target, "snmp-server community n3wCommunity RO")
    assert "n3wCommunity" not in result["diff"]
    assert "-ntp server 10.0.0.99" in result["diff"], "non-secret diff lines survive"
    assert result["redaction"]["linesRedacted"] == 1


def test_config_diff_include_secrets_returns_the_raw_diff(secretful_diff, eos_target):
    """Verifying that the literal key you are pushing is the one that lands is
    a real need; it just has to be asked for."""
    result = config_ops.config_diff(
        eos_target, "snmp-server community n3wCommunity RO", include_secrets=True
    )
    assert "n3wCommunity" in result["diff"]
    assert result["redaction"]["applied"] is False


def test_the_write_path_diff_is_redacted_with_no_opt_out(
    secretful_diff, eos_target, gov_home
):
    """A write's receipt has no business being how credentials leave the device."""
    result = config_ops.config_merge(eos_target, "snmp-server community n3wCommunity RO")
    assert "n3wCommunity" not in result["diff"]
    assert result["redaction"]["applied"] is True


def test_the_preview_diff_is_redacted_too(secretful_diff, eos_target, gov_home):
    result = config_ops.config_preview(
        eos_target, "snmp-server community n3wCommunity RO", replace=False, revert_in=300
    )
    assert "n3wCommunity" not in result["diff"]
    assert result["redaction"]["applied"] is True


def test_redaction_does_not_disturb_the_backup_digest(secretful_device, eos_target, gov_home):
    """The digest describes the RAW pre-change config, because that is what the
    undo replays. Hashing the redacted text would make it useless for that."""
    import hashlib

    result = config_ops.config_merge(eos_target, "ntp server 10.0.0.99")
    expected = hashlib.sha256(_CONFIG_WITH_SECRET.encode()).hexdigest()
    assert result["backup"]["sha256"] == expected
    assert result["backup"]["bytes"] == len(_CONFIG_WITH_SECRET)


# ── the CLI's deliberate asymmetry: -o writes RAW ───────────────────────────


@pytest.fixture
def device_cli(secretful_device, monkeypatch, tmp_path):
    """Point the CLI at the secret-bearing fake device."""
    from network_aiops.config import AppConfig, TargetConfig

    cfg = AppConfig(targets=[
        TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")
    ])
    monkeypatch.setattr("network_aiops.config.load_config", lambda path=None: cfg)
    monkeypatch.setenv("NETWORK_AIOPS_HOME", str(tmp_path))
    from network_aiops.cli import app

    return app


def test_cli_backup_to_stdout_masks_credentials(device_cli):
    """stdout is what an agent driving this CLI reads back. Same hazard as an
    MCP result, so the same default."""
    result = CliRunner().invoke(device_cli, ["config", "backup"])
    assert result.exit_code == 0, result.output
    assert "s3cr3tCommunity" not in result.output
    assert "hostname core-sw1" in result.output


def test_cli_backup_to_stdout_says_it_redacted(device_cli):
    """Visible, not silent — a human will not scroll back through 3000 lines
    for a JSON field, and neither will a model summarising the terminal."""
    result = CliRunner().invoke(device_cli, ["config", "backup"])
    assert "masked" in result.output
    assert "--include-secrets" in result.output


def test_cli_backup_include_secrets_prints_raw(device_cli):
    result = CliRunner().invoke(device_cli, ["config", "backup", "--include-secrets"])
    assert result.exit_code == 0, result.output
    assert "s3cr3tCommunity" in result.output


def test_cli_backup_to_a_file_writes_the_raw_config(device_cli, tmp_path):
    """THE deliberate exemption. A backup with its keys stripped is not a
    backup, and the operator named this path — it is not a context they were
    given by accident. Changing this to redact would break restores."""
    out = tmp_path / "backup.cfg"
    result = CliRunner().invoke(device_cli, ["config", "backup", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert Path(out).read_text() == _CONFIG_WITH_SECRET


def test_cli_backup_to_a_file_warns_what_the_file_holds(device_cli, tmp_path):
    out = tmp_path / "backup.cfg"
    result = CliRunner().invoke(device_cli, ["config", "backup", "-o", str(out)])
    assert "RAW config" in result.output


def test_cli_diff_masks_by_default_and_opts_out(device_cli, secretful_diff, tmp_path):
    snippet = tmp_path / "change.cfg"
    snippet.write_text("snmp-server community n3wCommunity RO\n")

    masked = CliRunner().invoke(device_cli, ["config", "diff", str(snippet)])
    assert masked.exit_code == 0, masked.output
    assert "n3wCommunity" not in masked.output

    raw = CliRunner().invoke(
        device_cli, ["config", "diff", str(snippet), "--include-secrets"]
    )
    assert raw.exit_code == 0, raw.output
    assert "n3wCommunity" in raw.output


# ── the governed twin carries the flag through ──────────────────────────────


def test_the_mcp_twin_defaults_to_redacted(secretful_device, gov_home, monkeypatch):
    from mcp_server.tools import config_ops as gov

    monkeypatch.setattr(gov, "_target", lambda name=None: _eos())
    result = gov.config_backup()
    assert "s3cr3tCommunity" not in result["config"]
    assert result["redaction"]["applied"] is True


def test_the_mcp_twin_honours_include_secrets(secretful_device, gov_home, monkeypatch):
    from mcp_server.tools import config_ops as gov

    monkeypatch.setattr(gov, "_target", lambda name=None: _eos())
    result = gov.config_backup(include_secrets=True)
    assert result["config"] == _CONFIG_WITH_SECRET


def _eos():
    from network_aiops.config import TargetConfig

    return TargetConfig(name="core-sw1", driver="eos", host="10.0.0.1", username="admin")


# ── the footgun the redaction itself creates ────────────────────────────────
#
# The obvious way to build a replacement config is "back it up, edit it, push
# it" — and a backup is now masked by default. Pushing that text back does not
# restore the credentials, it SETS them to the literal string '<redacted>'.
# The device accepts it and the diff looks like a clean edit. A guard shipped
# with the change that created the hazard.


def test_pushing_a_redacted_backup_is_refused(fake_driver_cls, eos_target, gov_home):
    from network_aiops.ops.config_ops import RedactedConfigPush

    text = f"hostname sw1\nsnmp-server community {PLACEHOLDER} RO\n"
    with pytest.raises(RedactedConfigPush):
        config_ops.config_replace(eos_target, text)


def test_the_refusal_says_what_would_have_happened_and_how_to_fix_it(
    fake_driver_cls, eos_target, gov_home
):
    from network_aiops.ops.config_ops import RedactedConfigPush

    with pytest.raises(RedactedConfigPush) as ei:
        config_ops.config_merge(eos_target, f"enable secret 5 {PLACEHOLDER}")
    msg = str(ei.value)
    assert "would not restore" in msg, "must correct the likely misconception"
    assert "include_secrets=True" in msg, "must name the route that works"
    assert "-o <path>" in msg, "must name the better route that works"


@pytest.mark.parametrize("fn,kwargs", [
    (config_ops.config_preview, {"replace": False, "revert_in": 300}),
    (config_ops.config_preview, {"replace": True, "revert_in": 300}),
])
def test_the_preview_refuses_it_too(fake_driver_cls, eos_target, gov_home, fn, kwargs):
    """A dry-run may read, never write — and it must not preview green a push
    the confirmed call would refuse."""
    from network_aiops.ops.config_ops import RedactedConfigPush

    with pytest.raises(RedactedConfigPush):
        fn(eos_target, f"snmp-server community {PLACEHOLDER} RO", **kwargs)


def test_config_diff_refuses_it_before_staging_a_candidate(fake_driver_cls, eos_target):
    """config_diff loads a candidate onto the device. Refuse before that, not
    after, so nothing is ever staged from placeholder text."""
    from network_aiops.ops.config_ops import RedactedConfigPush

    with pytest.raises(RedactedConfigPush):
        config_ops.config_diff(eos_target, f"enable secret 5 {PLACEHOLDER}")


def test_an_ordinary_config_push_is_unaffected(fake_driver_cls, eos_target, gov_home):
    """Exactness: the guard keys on the placeholder, not on the word 'secret'."""
    result = config_ops.config_merge(eos_target, "ntp server 10.0.0.99")
    assert result["committed"] is True


def test_the_guard_is_a_valueerror_so_the_cli_renders_it(fake_driver_cls):
    """CLI/MCP error handling keys off ValueError; keep it in that family."""
    from network_aiops.ops.config_ops import RedactedConfigPush

    assert issubclass(RedactedConfigPush, ValueError)
