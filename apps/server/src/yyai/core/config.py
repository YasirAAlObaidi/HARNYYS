"""Client configuration.

Each install reads one YAML file (path in YYAI_CONFIG). `${NAME}` and
`${NAME:-default}` are replaced from environment variables, so secrets stay in
the environment and never in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from yyai.core.errors import ConfigError

_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            found = os.environ.get(name, default)
            if found is None:
                raise ConfigError(f"Environment variable {name} is not set")
            return found

        return _ENV_REF.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


_HOURS = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class WorkingHours(BaseModel):
    """Opening hours in the client's timezone. Used only for the after-hours share on the Insights page.

    Each day is "HH:MM-HH:MM" (24-hour clock) or "closed". `confirmed: false` marks hours the client has not
    confirmed yet: the Insights page then says so next to the number.
    """

    confirmed: bool = False
    mon: str = "closed"
    tue: str = "closed"
    wed: str = "closed"
    thu: str = "closed"
    fri: str = "closed"
    sat: str = "closed"
    sun: str = "closed"

    @field_validator(*WEEKDAYS, mode="before")
    @classmethod
    def _check_day(cls, value: object) -> str:
        text_value = str(value).strip().lower()
        if text_value == "closed":
            return text_value
        if not _HOURS.match(text_value):
            raise ValueError(f"must be 'HH:MM-HH:MM' (24-hour clock) or 'closed', not {text_value!r}")
        if text_value[:5] >= text_value[6:]:
            raise ValueError(f"the opening time must be before the closing time: {text_value!r}")
        return text_value


class ClientConfig(BaseModel):
    name: str
    currency: str = "AED"
    timezone: str = "Asia/Dubai"
    working_hours: WorkingHours | None = None


class AuthConfig(BaseModel):
    """Staff logins for the web app (docs/decisions/0014). Every value has a safe default."""

    session_hours: float = Field(12.0, gt=0, description="A session ends this long after login, used or not")
    idle_minutes: float = Field(120.0, gt=0, description="A session also ends after this long with no request")
    failure_window_minutes: float = Field(15.0, gt=0)
    max_failures_per_user: int = Field(5, ge=1, description="Failed logins allowed per username in the window")
    max_failures_per_ip: int = Field(20, ge=1, description="Failed logins allowed per address in the window")


class ModelCapabilities(BaseModel):
    tools: bool = True
    vision: bool = False
    context_tokens: int = 8192


class ModelRoleConfig(BaseModel):
    provider: str = Field(description="Which model handler to use, e.g. openai_compat")
    base_url: str
    model: str
    api_key: str | None = None
    external: bool = Field(False, description="True if the endpoint is outside the client's building")
    allow_external: bool = Field(False, description="Client has agreed in writing to send data outside")
    timeout_s: float = 120.0
    params: dict[str, Any] = {}
    capabilities: ModelCapabilities = ModelCapabilities()


class BrandConfig(BaseModel):
    brand: str
    settings: dict[str, Any] = {}


class AgentConfig(BaseModel):
    system_prompt: str
    max_steps: int = 6
    history_messages: int = 20
    auto_send: bool = True
    fallback_reply: str | None = None
    # Approval rule per tool name, overriding the default from its risk class (docs/decisions/0008).
    approvals: dict[str, Literal["auto", "confirm"]] = {}


class WorkerConfig(BaseModel):
    poll_interval_s: float = 0.5
    turn_concurrency: int = 1
    catalogue_sync_interval_s: float = 3600.0
    # A turn still "running" after this long is assumed dead and put back in the queue. It MUST exceed the
    # longest possible turn: (agent.max_steps + 1 model calls) x the slowest model timeout_s, plus tool time.
    # If it is shorter, a healthy slow turn gets re-queued and the customer receives two replies.
    stale_after_s: float = 900.0
    outbox_max_attempts: int = 8


class Config(BaseModel):
    client: ClientConfig
    database_url: str
    models: dict[str, ModelRoleConfig]
    inventory: BrandConfig
    channels: dict[str, BrandConfig]
    agent: AgentConfig
    worker: WorkerConfig = WorkerConfig()
    auth: AuthConfig = AuthConfig()

    # Folder the config file lives in; relative paths in brand settings resolve from here.
    base_dir: Path = Path(".")


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path or os.environ.get("YYAI_CONFIG", "config.yaml")).resolve()
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = Config.model_validate(_expand(raw))
    config.base_dir = config_path.parent
    if "chat.default" not in config.models:
        raise ConfigError("models must define the role 'chat.default'")
    return config
