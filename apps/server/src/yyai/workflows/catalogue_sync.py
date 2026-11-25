"""Catalogue sync: copy the client's items into our database for fuzzy search."""

from __future__ import annotations

import logging

from yyai.services.catalogue import CatalogueService

logger = logging.getLogger(__name__)


class CatalogueSyncWorkflow:
    def __init__(self, catalogue: CatalogueService) -> None:
        self._catalogue = catalogue

    async def run(self) -> int:
        count = await self._catalogue.sync()
        logger.info("Catalogue synced: %s item(s)", count)
        return count
