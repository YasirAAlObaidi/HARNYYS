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
from pydantic import BaseModel, Field

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


class ClientConfig(BaseModel):
    name: str
    currency: str = "AED"
    timezone: str = "Asia/Dubai"


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
