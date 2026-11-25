"""Config loading, the worker defaults, and the startup check on stale_after_s."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from yyai.bootstrap import build
from yyai.core.config import WorkerConfig, load_config
from yyai.core.errors import ConfigError

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


def test_stale_after_defaults_to_15_minutes() -> None:
    assert WorkerConfig().stale_after_s == 900.0


def test_default_stale_window_outlasts_the_demo_configs_longest_turn(
    kahraman_dir: Path, demo_env: None
) -> None:
    config = load_config(kahraman_dir / "config.yaml")
    longest_turn_s = (config.agent.max_steps + 1) * max(role.timeout_s for role in config.models.values())
    assert config.worker.stale_after_s > longest_turn_s


def test_demo_config_loads_with_its_environment_filled_in(kahraman_dir: Path, demo_env: None) -> None:
    config = load_config(kahraman_dir / "config.yaml")
    assert config.database_url == "postgresql+psycopg://yyai:pw@postgres:5432/yyai"
    assert config.models["chat.default"].api_key == "key"
    assert config.channels["whatsapp"].settings["app_secret"] == "secret"
    assert config.base_dir == kahraman_dir.resolve()


def test_missing_environment_variable_is_a_config_error(
    kahraman_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in DEMO_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError, match="POSTGRES_PASSWORD"):
        load_config(kahraman_dir / "config.yaml")


def test_default_value_syntax(
    tmp_path: Path, kahraman_dir: Path, demo_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPTIONAL_THING", raising=False)
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["client"]["name"] = "${OPTIONAL_THING:-Fallback Name}"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert load_config(path).client.name == "Fallback Name"


def test_config_without_the_chat_default_role_is_refused(
    tmp_path: Path, kahraman_dir: Path, demo_env: None
) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["models"] = {"other.role": raw["models"]["chat.default"]}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"chat\.default"):
        load_config(path)


def test_missing_config_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


async def _build_with(
    kahraman_dir: Path, tmp_path: Path, stale_after_s: float | None, caplog: pytest.LogCaptureFixture
) -> None:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["inventory"] = {"brand": "file_catalogue", "settings": {"path": str(kahraman_dir / "catalogue.json")}}
    if stale_after_s is not None:
        raw["worker"] = {"stale_after_s": stale_after_s}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_config(path)
    with caplog.at_level(logging.WARNING, logger="yyai.bootstrap"):
        workflows = build(config)
    await workflows.aclose()


async def test_build_is_quiet_when_stale_after_is_long_enough(
    tmp_path: Path, kahraman_dir: Path, demo_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    await _build_with(kahraman_dir, tmp_path, None, caplog)
    assert "stale_after_s" not in caplog.text


async def test_build_warns_when_stale_after_is_shorter_than_a_possible_turn(
    tmp_path: Path, kahraman_dir: Path, demo_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    # 6 steps + the final answer = 7 model calls of up to 90 s each: 630 s. A 300 s window would re-queue live turns.
    await _build_with(kahraman_dir, tmp_path, 300, caplog)
    assert "stale_after_s" in caplog.text
    assert "630" in caplog.text


async def test_the_kahraman_config_builds_with_the_product_table(kahraman_dir: Path, demo_env: None) -> None:
    config = load_config(kahraman_dir / "config.yaml")
    assert config.inventory.brand == "sql_products"
    workflows = build(config)
    await workflows.aclose()


def test_the_kahraman_starter_sheet_has_no_problems(kahraman_dir: Path) -> None:
    import asyncio

    from yyai.services.products import ProductService

    class NoProductsYet:
        async def active_products(self) -> list:
            return []

    service = ProductService(NoProductsYet())  # type: ignore[arg-type]
    data = (kahraman_dir / "products.xlsx").read_bytes()
    report, records = asyncio.run(service.check(data, "products.xlsx"))
    assert report.issues == []
    assert len(records) == 190
    assert sum(record.price is not None for record in records) == 109  # the rest: hand over to staff
