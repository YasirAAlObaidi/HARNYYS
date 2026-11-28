"""The composition root: reads the client's config and wires everything together.

This is the one place allowed to import every layer (it is outside the
import-linter contracts on purpose). Choosing a brand for a job is a config
change: add an entry to the registries below, then name it in the config file.
See docs/decisions/0005.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from yyai.core.config import BrandConfig, Config, ModelRoleConfig
from yyai.core.errors import ConfigError
from yyai.handlers.integrations.file_catalogue.handler import FileCatalogue
from yyai.handlers.integrations.webchat.handler import WebChat
from yyai.handlers.integrations.whatsapp_cloud.handler import WhatsAppCloud
from yyai.handlers.model.openai_compat import OpenAICompatModel
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.persistence.conversations import ConversationStore
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.products import ProductStore
from yyai.handlers.persistence.requests import RequestStore
from yyai.handlers.ports import ChatModelPort, InventoryPort, MessagingPort
from yyai.services.catalogue import CatalogueService
from yyai.services.conversation import ConversationService
from yyai.services.messaging import MessagingService
from yyai.services.model import ModelService
from yyai.services.pricing import PricingService
from yyai.services.products import ProductService
from yyai.services.requests import RequestService
from yyai.workflows.agent.registry import ToolRegistry
from yyai.workflows.agent.request_tools import build_request_tools
from yyai.workflows.agent.tools import build_product_tools
from yyai.workflows.agent.turn import AgentTurnWorkflow
from yyai.workflows.catalogue_sync import CatalogueSyncWorkflow
from yyai.workflows.container import Workflows
from yyai.workflows.inbound import InboundWorkflow
from yyai.workflows.maintenance import MaintenanceWorkflow
from yyai.workflows.outbox import OutboxWorkflow
from yyai.workflows.products import ProductSheetWorkflow
from yyai.workflows.queries import ConversationQueries

logger = logging.getLogger(__name__)


# --- brand factories ---------------------------------------------------------
# Each takes the brand's `settings` from the config (plus what it needs to know
# about its place in the config) and returns a handler that fills one job.


def _setting(settings: Mapping[str, Any], key: str, brand: str, where: str) -> Any:
    value = settings.get(key)
    if value is None or value == "":
        raise ConfigError(f"{where}: brand '{brand}' needs the setting '{key}'")
    return value


def _file_catalogue(settings: Mapping[str, Any], base_dir: Path, products: ProductStore) -> FileCatalogue:
    path = Path(str(_setting(settings, "path", "file_catalogue", "inventory")))
    return FileCatalogue(path=base_dir / path)  # an absolute path stays as it is


def _sql_products(settings: Mapping[str, Any], base_dir: Path, products: ProductStore) -> ProductStore:
    """The product table in our database, loaded from the client's Excel sheet (`yyai products import`)."""
    return products


def _whatsapp_cloud(channel: str, settings: Mapping[str, Any]) -> WhatsAppCloud:
    images_dir = settings.get("images_dir")
    where = f"channels.{channel}"
    return WhatsAppCloud(
        channel=channel,
        phone_number_id=str(_setting(settings, "phone_number_id", "whatsapp_cloud", where)),
        access_token=str(_setting(settings, "access_token", "whatsapp_cloud", where)),
        app_secret=str(_setting(settings, "app_secret", "whatsapp_cloud", where)),
        verify_token=str(_setting(settings, "verify_token", "whatsapp_cloud", where)),
        graph_version=str(_setting(settings, "graph_version", "whatsapp_cloud", where)),
        images_dir=str(images_dir) if images_dir else None,
    )


def _webchat(channel: str, settings: Mapping[str, Any]) -> WebChat:
    return WebChat(channel=channel)


def _openai_compat(role: str, config: ModelRoleConfig) -> OpenAICompatModel:
    return OpenAICompatModel(base_url=config.base_url, api_key=config.api_key)


INVENTORY_BRANDS: dict[str, Callable[[Mapping[str, Any], Path, ProductStore], InventoryPort]] = {
    "file_catalogue": _file_catalogue,
    "sql_products": _sql_products,
}

MESSAGING_BRANDS: dict[str, Callable[[str, Mapping[str, Any]], MessagingPort]] = {
    "whatsapp_cloud": _whatsapp_cloud,
    "webchat": _webchat,
}

MODEL_PROVIDERS: dict[str, Callable[[str, ModelRoleConfig], ChatModelPort]] = {
    "openai_compat": _openai_compat,
}


def _choose[F](registry: Mapping[str, F], brand: str, where: str) -> F:
    try:
        return registry[brand]
    except KeyError:
        options = ", ".join(sorted(registry))
        raise ConfigError(f"{where}: unknown brand '{brand}'. Valid options: {options}") from None


def _build_inventory(config: Config, products: ProductStore) -> InventoryPort:
    brand: BrandConfig = config.inventory
    factory = _choose(INVENTORY_BRANDS, brand.brand, "inventory")
    return factory(brand.settings, config.base_dir, products)


def _build_channels(config: Config) -> dict[str, MessagingPort]:
    channels: dict[str, MessagingPort] = {}
    for name, brand in config.channels.items():
        factory = _choose(MESSAGING_BRANDS, brand.brand, f"channels.{name}")
        channels[name] = factory(name, brand.settings)
    return channels


def _build_providers(config: Config) -> dict[str, ChatModelPort]:
    providers: dict[str, ChatModelPort] = {}
    for role, role_config in config.models.items():
        factory = _choose(MODEL_PROVIDERS, role_config.provider, f"models.{role}")
        providers[role] = factory(role, role_config)
    return providers


def _warn_if_stale_window_too_short(config: Config) -> None:
    """A running turn older than `stale_after_s` is re-queued, so it must outlast the slowest possible turn."""
    slowest_model_s = max((role.timeout_s for role in config.models.values()), default=0.0)
    longest_turn_s = (config.agent.max_steps + 1) * slowest_model_s  # +1: the final answer without tools
    if config.worker.stale_after_s <= longest_turn_s:
        logger.warning(
            "worker.stale_after_s (%ss) is not longer than the longest possible turn "
            "((max_steps %s + 1) x model timeout %ss = %ss). A slow but healthy turn could be re-queued "
            "and answered twice. Raise stale_after_s.",
            config.worker.stale_after_s,
            config.agent.max_steps,
            slowest_model_s,
            longest_turn_s,
        )


def build(config: Config) -> Workflows:
    """Create every handler, service and workflow for this client.

    Needs no database connection: the engine and HTTP clients connect on first use.
    """
    closers: list[Any] = []

    db = Database(config.database_url)
    closers.append(db.aclose)

    product_store = ProductStore(db)
    inventory = _build_inventory(config, product_store)
    channels = _build_channels(config)
    providers = _build_providers(config)
    for handler in [inventory, *channels.values(), *providers.values()]:
        close = getattr(handler, "aclose", None)
        if close is not None:
            closers.append(close)

    conversations = ConversationService(ConversationStore(db))
    messaging = MessagingService(channels)
    catalogue = CatalogueService(inventory, CatalogueStore(db))
    pricing = PricingService(inventory)
    products = ProductService(
        product_store,
        currency=config.client.currency,
        vat_included=bool(config.inventory.settings.get("vat_included", True)),
    )
    model = ModelService(config.models, providers)

    requests = RequestService(RequestStore(db))

    registry = ToolRegistry(config.agent.approvals)
    for tool in [*build_product_tools(catalogue, pricing), *build_request_tools(catalogue, requests)]:
        registry.register(tool)
    registry.check_approvals()

    _warn_if_stale_window_too_short(config)

    logger.info(
        "Built yyai for %s: inventory=%s, channels=%s, tools=%s",
        config.client.name,
        config.inventory.brand,
        ", ".join(channels) or "none",
        ", ".join(spec.name for spec in registry.specs()),
    )
    return Workflows(
        inbound=InboundWorkflow(messaging, conversations),
        turns=AgentTurnWorkflow(
            conversations, model, registry, config.agent, config.client, requests=requests
        ),
        outbox=OutboxWorkflow(conversations, messaging, config.worker.outbox_max_attempts),
        catalogue_sync=CatalogueSyncWorkflow(catalogue),
        maintenance=MaintenanceWorkflow(conversations, config.worker.stale_after_s),
        queries=ConversationQueries(conversations),
        products=ProductSheetWorkflow(products, catalogue),
        closers=closers,
    )
