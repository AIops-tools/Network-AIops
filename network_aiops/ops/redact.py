"""Credential redaction for device configuration text.

A running config is the densest credential store on a network device: password
and ``secret`` hashes, SNMP community strings, SNMPv3 auth/priv material, IKE
pre-shared keys, RADIUS/TACACS keys, and BGP/keychain authentication keys. A
tool result goes straight into an agent transcript, so returning one hands all
of that to whatever else can read that context — the model provider, the session
log, and whoever the transcript is pasted to afterwards.

So this tool redacts by DEFAULT and the caller opts back in explicitly. What is
removed is the secret VALUE; the rest of the line survives, because
``username admin privilege 15 secret 5 <redacted>`` still answers the question
the operator usually had (which accounts exist), while carrying nothing worth
stealing.

**Honest limit: this is pattern matching over five vendor syntaxes, and pattern
matching misses things.** ``include_secrets=False`` REDUCES exposure; it is not
a guarantee that the text is free of credentials. The rules are line-oriented,
so the known blind spot is multi-line material — embedded PKI key blocks and
certificate chains have no per-line keyword to match on. Treat redacted output
as "safer to show", never as "cleared for publication". docs/VERIFICATION.md
carries the full list of what has and has not been checked against real gear.
"""

from __future__ import annotations

import re

PLACEHOLDER = "<redacted>"

# A secret value: a quoted Junos string, or a bare token. ';' is excluded from
# the bare form so Junos' statement terminator survives redaction.
_TOKEN = r'"[^"]*"|[^\s;]+'

# Encryption/format markers that sit between a keyword and the value. Each is
# OPTIONAL and the trailing group backtracks, so a secret that merely looks
# like a type code (a numeric key-string, say) is still the token redacted.
_HASH_TYPE = r"(?:\s+(?:encrypted|sha512|sha384|sha256|sha1|sha|md5|\d+)\b)*"
_KEY_TYPE = (
    r"(?:\s+(?:encrypted|ascii-text|hexadecimal|plain-text|cleartext|ascii|hex|"
    r"md5|sha1|sha|hmac-[\w-]+|\d+)\b)*"
)
# Deliberately NOT \d+: a numeric community string is plausible, and eating it
# as a type code would redact the next token and leak the community itself.
_COMMUNITY_TYPE = r"(?:\s+(?:encrypted|0|7)\b)?"
# SNMPv3 requires an algorithm between the keyword and the key, which is what
# separates 'auth md5 <key>' from 'aaa authentication login default ...'.
_SNMPV3_ALGO = r"(?:\s+(?:md5|sha512|sha384|sha256|sha224|sha1|sha|3des|des|aes)\b)(?:\s+\d+\b)?"

_RULES: tuple[re.Pattern[str], ...] = (
    # password / secret / passwd.
    # Cisco IOS   'enable secret 5 $1$..'   'username u password 7 08701E1D'
    # IOS-XR      'password encrypted 0202..'
    # NX-OS       'username admin password 5 $5$..'
    # Arista EOS  'username admin secret sha512 $6$..'
    # Junos       'encrypted-password "$6$.."'  ('-' is a word boundary, so the
    #             same rule covers encrypted-password / plain-text-password)
    re.compile(rf"(?i)\b(?:password|passwd|secret)\b{_HASH_TYPE}\s+(?P<secret>{_TOKEN})"),
    # SNMP community strings.
    # IOS/EOS/XR  'snmp-server community public RO'
    # NX-OS       'snmp-server community public group network-operator'
    # Junos       'set snmp community public authorization read-only'
    re.compile(rf"(?i)\bcommunity(?:-string)?\b{_COMMUNITY_TYPE}\s+(?P<secret>{_TOKEN})"),
    # SNMPv3 auth/priv key material, when an algorithm names the digest.
    # 'snmp-server user u auth md5 <key> priv aes 128 <key>'
    re.compile(
        rf"(?i)\b(?:auth|authentication|priv|privacy)\b{_SNMPV3_ALGO}\s+(?P<secret>{_TOKEN})"
    ),
    # NX-OS writes localised SNMPv3 digests as bare 0x hex with the algorithm
    # optional: 'auth md5 0x1a2b priv 0x3c4d localizedkey'. Matching on the 0x
    # shape keeps this precise enough to leave ordinary 'priv' words alone.
    re.compile(
        r"(?i)\b(?:auth|authentication|priv|privacy)\b"
        r"(?:\s+(?:md5|sha\d*|aes(?:-\d+)?|3des|des)\b)?(?:\s+\d+\b)?"
        r"\s+(?P<secret>0x[0-9a-f]+)"
    ),
    # Named key keywords: IKE PSKs, keychains, RADIUS/TACACS/BGP/OSPF auth keys.
    re.compile(
        rf"(?i)\b(?:pre-shared-key|preshared-key|authentication-key|privacy-key|"
        rf"key-string|key-hash|shared-secret|message-digest-key|radius-key|"
        rf"tacacs-key|wpa-psk)\b{_KEY_TYPE}\s+(?P<secret>{_TOKEN})"
    ),
    # A bare 'key' in a credential-server context, encrypted or not. The
    # tempered dot stops the scan at the FIRST 'key' so intervening options
    # ('host 1.2.3.4 port 49') cannot swallow it:
    #   'tacacs-server key MyTacKey'            (no type code at all)
    #   'crypto isakmp key <psk> address 1.2.3.4'
    #   'radius-server host 1.2.3.4 auth-port 1812 key 7 <hash>'
    re.compile(
        rf"(?i)\b(?:radius|tacacs|isakmp|keyring|ipsec)[\w+-]*\b"
        rf"(?:(?!\bkey\b).)*?\bkey\b{_KEY_TYPE}\s+(?P<secret>{_TOKEN})"
    ),
    # A bare 'key' elsewhere ONLY when an explicit encryption-type code follows.
    # That is what distinguishes a keychain's 'key 7 <hash>' from 'key chain
    # FOO' and 'crypto key generate rsa', which carry no secret at all.
    re.compile(rf"(?i)\bkey\s+(?:encrypted|[05-9])\s+(?P<secret>{_TOKEN})"),
    # Junos annotates every secret-bearing statement itself. The cheapest true
    # positive in the set, and the only vendor-supplied one — it catches
    # statements whose keyword none of the rules above knows about.
    re.compile(rf"(?P<secret>{_TOKEN})\s*;?\s*##\s*SECRET-DATA"),
)


def _mask(match: re.Match[str]) -> str:
    """Replace only the ``secret`` group, leaving the rest of the match intact."""
    whole, base = match.group(0), match.start()
    start, end = match.span("secret")
    return whole[: start - base] + PLACEHOLDER + whole[end - base :]


def redact_line(line: str) -> str:
    """Return ``line`` with every recognised credential value masked."""
    for rule in _RULES:
        line = rule.sub(_mask, line)
    return line


def redact_config(text: str | None) -> tuple[str, int]:
    """Mask credential values in config/diff text.

    Returns ``(redacted_text, lines_redacted)``. The count is the number of
    LINES changed, not the number of values masked — it exists so the caller can
    see that a transformation happened at all. A silent transformation is a
    defect in this line; the caller must always be able to tell that what it is
    reading is not what the device said.
    """
    if not text:
        return "", 0
    redacted_lines = 0
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        masked = redact_line(line)
        if masked != line:
            redacted_lines += 1
        out.append(masked)
    return "".join(out), redacted_lines


def redaction_note(lines_redacted: int, *, applied: bool) -> str:
    """The caller-facing explanation of what was done to the text, and how to opt out."""
    if not applied:
        return (
            "NOT REDACTED — include_secrets=True was requested, so this text is the "
            "device's verbatim config including credential hashes, SNMP communities, "
            "pre-shared keys and RADIUS/TACACS keys. It is now in this transcript."
        )
    if lines_redacted == 0:
        return (
            "Redaction ran and matched nothing, so no line was changed. That is not "
            "proof the text is credential-free: the rules are patterns over five "
            "vendor syntaxes and cannot see multi-line key blocks. Pass "
            "include_secrets=True to get the verbatim text."
        )
    return (
        f"{lines_redacted} line(s) had credential values replaced with "
        f"'{PLACEHOLDER}' — password/secret hashes, SNMP communities, pre-shared "
        f"keys, RADIUS/TACACS and keychain keys. Pattern-based over five vendor "
        f"syntaxes, so this REDUCES exposure rather than guaranteeing none remains. "
        f"Pass include_secrets=True for the verbatim text, or use the CLI's "
        f"'-o <path>' flag, which writes the raw config to a file instead of here."
    )
