"""Tests for the ``network-aiops init`` onboarding wizard.

Driven end-to-end through Typer's CliRunner against an isolated
``NETWORK_AIOPS_HOME`` — nothing touches the real ``~/.network-aiops`` and no
device connection is ever attempted (the closing doctor prompt is declined).
"""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

import network_aiops.cli.init as init_mod
import network_aiops.config as config_mod
import network_aiops.secretstore as ss
from network_aiops.cli._root import app

pytestmark = pytest.mark.unit

MASTER_PW = "wizard-master-pw"
runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point every path constant the wizard touches at a throwaway home."""
    config_file = tmp_path / "config.yaml"
    monkeypatch.setenv("NETWORK_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv(ss.MASTER_PASSWORD_ENV, MASTER_PW)

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(init_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    return tmp_path


@pytest.fixture
def fake_getpass(monkeypatch):
    """The wizard reads hidden values via getpass (bypasses stdin)."""

    def _fake(prompt: str = "") -> str:
        if "Enable secret" in prompt:
            return "enable-pw"
        if "NetBox" in prompt:
            return "nb-token-xyz"
        return "device-pw-123"

    monkeypatch.setattr("getpass.getpass", _fake)


def _run_init(answers: list[str]):
    return runner.invoke(app, ["init"], input="".join(a + "\n" for a in answers))


# name, driver, host, username, port(skip), transport(skip), enable secret?,
# add another?, configure NetBox?, run doctor?
HAPPY_ANSWERS = ["core-sw1", "ios", "192.0.2.10", "admin", "", "", "n", "n", "n", "n"]


def test_wizard_writes_config_to_isolated_home(isolated_home, fake_getpass):
    result = _run_init(HAPPY_ANSWERS)
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["devices"] == [
        {
            "name": "core-sw1",
            "driver": "ios",
            "host": "192.0.2.10",
            "username": "admin",
        }
    ]
    assert "netbox" not in raw


def test_secret_lands_encrypted_not_in_config(isolated_home, fake_getpass):
    _run_init(HAPPY_ANSWERS)

    config_text = (isolated_home / "config.yaml").read_text("utf-8")
    assert "device-pw-123" not in config_text
    secrets_blob = (isolated_home / "secrets.enc").read_text("utf-8")
    assert "device-pw-123" not in secrets_blob
    assert ss.SecretStore.unlock(MASTER_PW).get("core-sw1") == "device-pw-123"


def test_rules_yaml_seeded_with_approver_tier(isolated_home, fake_getpass):
    _run_init(HAPPY_ANSWERS)

    rules = (isolated_home / "rules.yaml").read_text("utf-8")
    assert "high-risk-requires-approver" in rules
    assert "risk_tiers" in rules


def test_rerun_does_not_clobber_existing_rules(isolated_home, fake_getpass):
    (isolated_home / "rules.yaml").write_text("# operator-authored\n", "utf-8")
    answers = ["edge-r1", "junos", "192.0.2.20", "admin", "", "", "n", "n", "n", "n"]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    assert (isolated_home / "rules.yaml").read_text("utf-8") == "# operator-authored\n"


def test_driver_defaults_to_ios_on_enter(isolated_home, fake_getpass):
    # Accept the driver prompt with a bare Enter — the default must be ios.
    answers = ["core-sw1", "", "192.0.2.10", "admin", "", "", "n", "n", "n", "n"]
    _run_init(answers)
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["devices"][0]["driver"] == "ios"


def test_unsupported_driver_reprompts(isolated_home, fake_getpass):
    answers = ["core-sw1", "cisco", "eos", "192.0.2.10", "admin", "", "", "n", "n", "n", "n"]
    result = _run_init(answers)
    assert "'cisco' is not supported" in result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["devices"][0]["driver"] == "eos"


def test_optional_port_and_transport_recorded(isolated_home, fake_getpass):
    answers = ["core-sw1", "ios", "192.0.2.10", "admin", "830", "ssh", "n", "n", "n", "n"]
    _run_init(answers)
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["devices"][0]["optional_args"] == {"port": 830, "transport": "ssh"}


def test_non_numeric_port_skipped_with_warning(isolated_home, fake_getpass):
    answers = ["core-sw1", "ios", "192.0.2.10", "admin", "abc", "", "n", "n", "n", "n"]
    result = _run_init(answers)
    assert "Port must be a number" in result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert "optional_args" not in raw["devices"][0]


def test_enable_secret_recorded_in_optional_args(isolated_home, fake_getpass):
    # By design NAPALM's optional_args.secret lives in config.yaml (chmod 700
    # dir); the wizard prints a note saying exactly that.
    answers = ["core-sw1", "ios", "192.0.2.10", "admin", "", "", "y", "n", "n", "n"]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["devices"][0]["optional_args"] == {"secret": "enable-pw"}


def test_empty_password_means_key_auth_and_no_store(isolated_home, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    result = _run_init(HAPPY_ANSWERS)
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "no password — key auth" in out
    assert not (isolated_home / "secrets.enc").exists()


def test_existing_device_kept_when_overwrite_declined(isolated_home, fake_getpass):
    _run_init(HAPPY_ANSWERS)
    # Re-add the same name, decline overwrite, then add a fresh device.
    answers = [
        "core-sw1",  # duplicate name
        "n",  # overwrite? -> no, loop restarts
        "edge-r1",
        "junos",
        "203.0.113.1",
        "admin",
        "",  # port
        "",  # transport
        "n",  # enable secret?
        "n",  # add another?
        "n",  # netbox?
        "n",  # doctor?
    ]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    names = [d["name"] for d in raw["devices"]]
    assert names == ["core-sw1", "edge-r1"]
    # Original device untouched.
    assert raw["devices"][0]["host"] == "192.0.2.10"


def test_existing_device_replaced_when_overwrite_accepted(isolated_home, fake_getpass):
    _run_init(HAPPY_ANSWERS)
    answers = ["core-sw1", "y", "eos", "198.51.100.5", "ops", "", "", "n", "n", "n", "n"]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert len(raw["devices"]) == 1
    assert raw["devices"][0] == {
        "name": "core-sw1",
        "driver": "eos",
        "host": "198.51.100.5",
        "username": "ops",
    }


def test_add_another_device_loops(isolated_home, fake_getpass):
    answers = [
        "core-sw1", "ios", "192.0.2.10", "admin", "", "", "n",
        "y",  # add another?
        "edge-r1", "junos", "203.0.113.1", "admin", "", "", "n",
        "n",  # add another?
        "n",  # netbox?
        "n",  # doctor?
    ]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert [d["name"] for d in raw["devices"]] == ["core-sw1", "edge-r1"]


def test_netbox_configured_with_encrypted_token(isolated_home, fake_getpass):
    answers = [
        "core-sw1", "ios", "192.0.2.10", "admin", "", "", "n",
        "n",  # add another?
        "y",  # configure NetBox?
        "https://netbox.example.com",
        "n",  # doctor?
    ]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["netbox"] == {"url": "https://netbox.example.com"}
    config_text = (isolated_home / "config.yaml").read_text("utf-8")
    assert "nb-token-xyz" not in config_text
    store = ss.SecretStore.unlock(MASTER_PW)
    assert store.get(ss.NETBOX_TOKEN_NAME) == "nb-token-xyz"


def test_declining_doctor_prompt_skips_connectivity(isolated_home, fake_getpass, monkeypatch):
    def _boom(*a, **k):  # pragma: no cover — must not be reached
        raise AssertionError("run_doctor must not run when declined")

    monkeypatch.setattr("network_aiops.doctor.run_doctor", _boom)
    result = _run_init(HAPPY_ANSWERS)
    assert result.exit_code == 0, result.output


def test_accepting_doctor_prompt_runs_it(isolated_home, fake_getpass, monkeypatch):
    calls: list[dict] = []

    def _fake_doctor(*a, **k) -> int:
        calls.append(k)
        return 0

    monkeypatch.setattr("network_aiops.doctor.run_doctor", _fake_doctor)
    answers = ["core-sw1", "ios", "192.0.2.10", "admin", "", "", "n", "n", "n", "y"]
    result = _run_init(answers)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
