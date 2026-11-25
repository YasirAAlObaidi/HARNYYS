"""Product sheet import and export: the client's Excel file is how the product table gets its prices and stock."""

from __future__ import annotations

import logging

from yyai.core.types import ProductImportReport
from yyai.services.catalogue import CatalogueService
from yyai.services.products import ProductService

logger = logging.getLogger(__name__)


class ProductSheetWorkflow:
    def __init__(self, products: ProductService, catalogue: CatalogueService) -> None:
        self._products = products
        self._catalogue = catalogue

    async def import_sheet(
        self,
        data: bytes,
        *,
        source: str,
        imported_by: str | None = None,
        apply: bool = False,
        allow_mass_deactivation: bool = False,
    ) -> ProductImportReport:
        """Check a sheet and, when `apply` is set and it has no problems, load it.

        Without `apply` this is a preview: it reports what would be added, changed and switched off. Raises
        InvalidFile (a ValueError) when the file is not a spreadsheet at all.
        """
        report, records = await self._products.check(
            data, source, allow_mass_deactivation=allow_mass_deactivation
        )
        if report.issues or not apply:
            return report
        report = await self._products.apply(report, records, imported_by)
        logger.info(
            "Product sheet %s imported by %s: %s added, %s updated, %s switched off, %s unchanged",
            source,
            imported_by or "unknown",
            len(report.added),
            len(report.updated),
            len(report.deactivated),
            report.unchanged,
        )
        # Refresh the search copy now, so the agent finds new items at once rather than at the next timed sync.
        await self._catalogue.sync()
        return report

    async def export_sheet(self) -> bytes:
        """The product table as an Excel file, in the layout the import reads."""
        return await self._products.export()
