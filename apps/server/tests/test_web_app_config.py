"""Config and command line for the web app: working hours, the reserved staff channel, `yyai users`."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pyotp
import pytest
import yaml

from yyai import cli
from yyai.bootstrap import build
from yyai.core.config import load_config
from yyai.core.errors import ConfigError
from yyai.core.types import NewStaffUser, StaffRole, StaffUser

DEMO_ENV = {
    "POSTGRES_PASSWORD": "pw",
    "MODEL_API_KEY": "key",
    "WHATSAPP_PHONE_NUMBER_ID": "123",
    "WHATSAPP_ACCESS_TOKEN": "tok",
    "WHATSAPP_APP_SECRET": "secret",
    "WHATSAPP_VERIFY_TOKEN": "verify",
}


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in DEMO_ENV.items():
        monkeypatch.setenv(name, value)


def write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def test_kahramans_working_hours_are_a_marked_placeholder(kahraman_dir: Path, demo_env: None) -> None:
    config = load_config(kahraman_dir / "config.yaml")
    hours = config.client.working_hours
    assert hours is not None and hours.confirmed is False  # until Kahraman confirms them
    assert "PLACEHOLDER" in (kahraman_dir / "config.yaml").read_text(encoding="utf-8")
    assert config.auth.session_hours == 12 and config.auth.max_failures_per_user == 5


def test_bad_working_hours_are_a_config_error(tmp_path: Path, kahraman_dir: Path, demo_env: None) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["client"]["working_hours"]["mon"] = "9 to 6"
    with pytest.raises(ValueError, match="HH:MM-HH:MM"):
        load_config(write(tmp_path, raw))


async def test_staff_is_a_built_in_channel_and_cannot_be_configured(
    tmp_path: Path, kahraman_dir: Path, demo_env: None
) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["channels"]["staff"] = {"brand": "webchat"}
    with pytest.raises(ConfigError, match="built-in staff"):
        build(load_config(write(tmp_path, raw)))


async def test_an_unknown_timezone_fails_at_startup(tmp_path: Path, kahraman_dir: Path, demo_env: None) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["client"]["timezone"] = "Mars/Olympus"
    with pytest.raises(ConfigError, match="timezone"):
        build(load_config(write(tmp_path, raw)))


# --- yyai users ----------------------------------------------------------------------------------------------------


def test_the_enrolment_shows_the_key_link_and_qr_once() -> None:
    from datetime import UTC, datetime

    secret = pyotp.random_base32()
    created = NewStaffUser(
        user=StaffUser(id=1, username="yasir", role=StaffRole.ADMIN, created_at=datetime.now(UTC)),
        totp_secret=secret,
        totp_uri=pyotp.TOTP(secret).provisioning_uri(name="yasir", issuer_name="Kahraman yyai"),
    )

    text = cli.format_enrolment(created, qr=True)

    assert "Staff user 'yasir' (admin) is ready." in text
    assert " ".join(secret[i : i + 4] for i in range(0, len(secret), 4)) in text
    assert created.totp_uri in text
    assert "█" in text or "▀" in text or "▄" in text  # the QR code, drawn with block characters
    assert "█" not in cli.format_enrolment(created, qr=False)


@pytest.mark.db
def test_users_add_list_disable_and_reset_from_the_command_line(
    tmp_path: Path,
    kahraman_dir: Path,
    clean_database: str,
    demo_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["database_url"] = clean_database
    monkeypatch.setenv("YYAI_CONFIG", str(write(tmp_path, raw)))

    def run(*argv: str, stdin: str = "") -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return cli.run(list(argv))

    assert run("users", "add", "Yasir", "--role", "admin", "--display-name", "Yasir A.", stdin="a long password 1\n") == 0
    out = capsys.readouterr().out
    assert "Staff user 'yasir' (admin) is ready." in out and "otpauth://totp/" in out

    assert run("users", "add", "yasir", "--role", "sales", stdin="a long password 2\n") == cli.EXIT_USER_PROBLEM
    assert "already exists" in capsys.readouterr().err
    assert run("users", "add", "omar", "--role", "sales", stdin="short\n") == cli.EXIT_USER_PROBLEM
    assert "at least 12" in capsys.readouterr().err

    assert run("users", "disable", "yasir") == 0
    capsys.readouterr()
    assert run("users", "list") == 0
    assert "yasir" in (listing := capsys.readouterr().out) and "(disabled)" in listing and "never" in listing
    assert run("users", "reset", "yasir", stdin="another long password\n") == 0
    assert "otpauth://" in capsys.readouterr().out
    assert run("users", "reset", "nobody", stdin="another long password\n") == cli.EXIT_USER_PROBLEM
    assert run("users", "enable", "nobody") == cli.EXIT_USER_PROBLEM
