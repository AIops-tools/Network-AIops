"""Tests for ``network_aiops.doctor.run_doctor``.

All filesystem paths are redirected to a tmp dir and the connection layer is
mocked at the ``device_session`` / ``netbox_api`` boundary — no test ever
touches a real network device, NetBox, or the real ``~/.network-aiops``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

import network_aiops.config as config_mod
import network_aiops.doctor as doctor_mod
import network_aiops.secretstore as ss
from network_aiops.doctor import run_doctor

pytestmark = pytest.mark.unit

MASTER_PW = "test-master-pw"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect every config/secret path constant at a throwaway directory."""
    config_file = tmp_path / "config.yaml"
    env_file = tmp_path / ".env"
    secrets_file = tmp_path / "secrets.enc"

    monkeypatch.setenv("NETWORK_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv(ss.MASTER_PASSWORD_ENV, MASTER_PW)

    # config module reads its globals at call time.
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "ENV_FILE", env_file)
    # doctor imported the names directly; patch its namespace too.
    monkeypatch.setattr(doctor_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(doctor_mod, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor_mod, "SECRETS_FILE", secrets_file)
    # secret store paths + cache.
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", env_file)
    monkeypatch.setattr(ss, "_cached", None)
    return tmp_path


def _write_config(home, devices: list[dict], netbox: dict | None = None) -> None:
    data: dict = {"devices": devices}
    if netbox:
        data["netbox"] = netbox
    (home / "config.yaml").write_text(yaml.safe_dump(data), "utf-8")


def _device(name: str = "core-sw1") -> dict:
    return {"name": name, "driver": "ios", "host": "192.0.2.10", "username": "admin"}


def _store_secret(name: str = "core-sw1", value: str = "device-pw") -> None:
    ss.SecretStore.unlock(MASTER_PW).set(name, value)


@pytest.fixture
def ok_session(monkeypatch):
    """A device_session whose driver answers get_facts happily."""
    dev = MagicMock(name="napalm_driver")
    dev.get_facts.return_value = {"model": "C9300-24T", "os_version": "17.9.4"}
    session = MagicMock(name="device_session")
    session.return_value.__enter__.return_value = dev
    monkeypatch.setattr("network_aiops.connection.device_session", session)
    return session


def _normalized(capsys) -> str:
    """Rich wraps long lines containing tmp paths; collapse whitespace."""
    return " ".join(capsys.readouterr().out.split())


def test_missing_config_file_warns_and_fails_on_no_devices(isolated_home, capsys):
    assert run_doctor(skip_auth=True) == 1
    out = _normalized(capsys)
    assert "No config file" in out
    assert "No devices configured" in out


def test_config_load_failure_reported_not_raised(isolated_home, capsys):
    # A device without the required 'name' key makes load_config raise; the
    # doctor must report the failure as a check, never a traceback.
    _write_config(isolated_home, [{"host": "192.0.2.10"}])
    assert run_doctor() == 1
    assert "Config load failed" in capsys.readouterr().out


def test_no_devices_configured(isolated_home, capsys):
    _write_config(isolated_home, [])
    assert run_doctor() == 1
    assert "No devices configured" in capsys.readouterr().out


def test_all_healthy_exits_zero(isolated_home, ok_session, capsys):
    _write_config(isolated_home, [_device()])
    _store_secret()
    assert run_doctor() == 0
    out = _normalized(capsys)
    assert "Config file present" in out
    assert "Encrypted secret store present" in out
    assert "1 device(s) configured" in out
    assert "core-sw1 (ios@192.0.2.10) — password: set" in out
    assert "Reachable 'core-sw1' (model C9300-24T, os 17.9.4)" in out
    ok_session.assert_called_once()
    assert ok_session.call_args[0][0].name == "core-sw1"


def test_skip_auth_never_touches_connection_layer(isolated_home, monkeypatch, capsys):
    _write_config(isolated_home, [_device()])
    _store_secret()

    def _boom(*a, **k):  # pragma: no cover — must not be reached
        raise AssertionError("connection layer must not be used with --skip-auth")

    monkeypatch.setattr("network_aiops.connection.device_session", _boom)
    monkeypatch.setattr("network_aiops.connection.netbox_api", _boom)
    assert run_doctor(skip_auth=True) == 0
    assert "Skipping connectivity check" in capsys.readouterr().out


def test_missing_password_is_warned_not_fatal(isolated_home, capsys):
    # An empty password is valid for key-based SSH auth, so a missing secret
    # is surfaced as status, not counted as a problem.
    _write_config(isolated_home, [_device()])
    _store_secret("other-device")  # store exists, but not for this device
    assert run_doctor(skip_auth=True) == 0
    out = _normalized(capsys)
    assert "core-sw1 (ios@192.0.2.10) — password: missing (key-auth or run init)" in out


def test_no_secret_store_yet_warns(isolated_home, capsys):
    _write_config(isolated_home, [_device()])
    assert run_doctor(skip_auth=True) == 0
    out = _normalized(capsys)
    assert "No encrypted secret store yet" in out
    assert "password: missing" in out


def test_legacy_env_file_warns_but_env_password_passes(isolated_home, monkeypatch, capsys):
    _write_config(isolated_home, [_device()])
    (isolated_home / ".env").write_text("NETWORK_CORE_SW1_PASSWORD=legacy\n")
    monkeypatch.setenv("NETWORK_CORE_SW1_PASSWORD", "legacy")
    assert run_doctor(skip_auth=True) == 0
    out = _normalized(capsys)
    assert "legacy plaintext .env" in out
    assert "password: set (NETWORK_CORE_SW1_PASSWORD)" in out


def test_connect_failure_reported_per_device(isolated_home, monkeypatch, capsys):
    _write_config(isolated_home, [_device("sw-a"), _device("sw-b")])
    _store_secret("sw-a")
    _store_secret("sw-b")

    dev = MagicMock(name="napalm_driver")
    dev.get_facts.return_value = {"model": "vEOS", "os_version": "4.32"}
    ok_cm = MagicMock()
    ok_cm.__enter__.return_value = dev

    def _session(target):
        if target.name == "sw-b":
            raise ConnectionError("connection refused")
        return ok_cm

    monkeypatch.setattr("network_aiops.connection.device_session", _session)
    assert run_doctor() == 1
    out = _normalized(capsys)
    assert "Reachable 'sw-a'" in out
    assert "Connect to 'sw-b' failed: connection refused" in out


def test_permission_warning_surfaced(isolated_home, capsys):
    _write_config(isolated_home, [_device()])
    _store_secret()
    (isolated_home / "secrets.enc").chmod(0o644)
    assert run_doctor(skip_auth=True) == 0
    # Rich wraps long lines; normalize whitespace before matching.
    out = _normalized(capsys)
    assert "should be 600" in out


def test_netbox_configured_and_reachable(isolated_home, ok_session, monkeypatch, capsys):
    _write_config(isolated_home, [_device()], netbox={"url": "https://netbox.example.com"})
    _store_secret()
    _store_secret("netbox-token", "nb-token")
    api = MagicMock(name="pynetbox_api")
    monkeypatch.setattr("network_aiops.connection.netbox_api", MagicMock(return_value=api))
    assert run_doctor() == 0
    out = _normalized(capsys)
    assert "NetBox configured: https://netbox.example.com (token set)" in out
    assert "NetBox reachable" in out
    api.status.assert_called_once_with()


def test_netbox_failure_reported_as_problem(isolated_home, ok_session, monkeypatch, capsys):
    _write_config(isolated_home, [_device()], netbox={"url": "https://netbox.example.com"})
    _store_secret()
    _store_secret("netbox-token", "nb-token")
    api = MagicMock(name="pynetbox_api")
    api.status.side_effect = RuntimeError("401 unauthorized")
    monkeypatch.setattr("network_aiops.connection.netbox_api", MagicMock(return_value=api))
    assert run_doctor() == 1
    out = _normalized(capsys)
    assert "Reachable 'core-sw1'" in out
    assert "NetBox check failed: 401 unauthorized" in out


def test_netbox_token_missing_flagged(isolated_home, capsys):
    _write_config(isolated_home, [_device()], netbox={"url": "https://netbox.example.com"})
    _store_secret()  # device password present; netbox-token absent
    assert run_doctor(skip_auth=True) == 0
    out = _normalized(capsys)
    assert "NetBox configured: https://netbox.example.com (token MISSING)" in out
