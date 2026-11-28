"""The `yyai` command: load the client's product sheet and export the table again.

    yyai products import products.xlsx            # preview: what would be added, changed, switched off
    yyai products import products.xlsx --apply    # load it
    yyai products export products.xlsx            # the current table, in the same layout

On a client box, inside Docker (the client folder is mounted at /config):

    docker compose -f deploy/compose.yaml run --rm server yyai products import /config/products.xlsx --apply

Like main.py and worker.py, this is a composition root: it reads the config and wires everything with
yyai.bootstrap, then calls one workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from yyai.bootstrap import build
from yyai.core.config import load_config
from yyai.core.errors import InvalidFile
from yyai.core.logging import configure_logging
from yyai.core.types import ProductImportReport
from yyai.workflows.products import ProductSheetWorkflow

EXIT_OK = 0
EXIT_SHEET_PROBLEMS = 1
EXIT_UNREADABLE = 2
SHOW_CODES = 10  # list at most this many codes per group; the counts are always complete


def main() -> None:
    sys.exit(run(sys.argv[1:]))


def run(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    configure_logging()
    return asyncio.run(_dispatch(args))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yyai", description="yyai command line")
    commands = parser.add_subparsers(dest="command", required=True)

    products = commands.add_parser("products", help="the product table and its Excel sheet")
    actions = products.add_subparsers(dest="action", required=True)

    load = actions.add_parser("import", help="check a product sheet and, with --apply, load it")
    load.add_argument("file", type=Path, help="the .xlsx file")
    load.add_argument(
        "--apply", action="store_true", help="load the sheet (without it, only show the changes)"
    )
    load.add_argument(
        "--allow-mass-deactivation",
        action="store_true",
        help="allow a sheet that switches off more than half of the products on sale",
    )
    load.add_argument("--by", help="who is importing, for the import log")

    save = actions.add_parser("export", help="write the product table to an .xlsx file")
    save.add_argument("file", type=Path, help="where to write the .xlsx file")
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    workflows = build(load_config())
    try:
        if args.action == "import":
            return await _import(workflows.products, args)
        data = await workflows.products.export_sheet()
        args.file.write_bytes(data)
        print(f"Wrote {args.file}")
        return EXIT_OK
    finally:
        await workflows.aclose()


async def _import(products: ProductSheetWorkflow, args: argparse.Namespace) -> int:
    try:
        data = args.file.read_bytes()
    except OSError as exc:
        print(f"Cannot read {args.file}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        report = await products.import_sheet(
            data,
            source=args.file.name,
            imported_by=args.by,
            apply=args.apply,
            allow_mass_deactivation=args.allow_mass_deactivation,
        )
    except InvalidFile as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNREADABLE
    print(format_report(report))
    return EXIT_SHEET_PROBLEMS if report.issues else EXIT_OK


def format_report(report: ProductImportReport) -> str:
    """The import result as plain text for the terminal."""
    lines = [f"Sheet: {report.source} ({report.rows} products read)"]
    if report.issues:
        lines.append("")
        lines.append(f"{len(report.issues)} problem(s). Nothing was changed. Fix the sheet and try again:")
        for issue in report.issues:
            where = ", ".join(
                part for part in (f"row {issue.row}" if issue.row else None, issue.column) if part
            )
            lines.append(f"  - {where + ': ' if where else ''}{issue.message}")
    for label, codes in (
        ("New", report.added),
        ("Changed", report.updated),
        ("Switched off", report.deactivated),
    ):
        shown = ", ".join(codes[:SHOW_CODES]) + (" ..." if len(codes) > SHOW_CODES else "")
        lines.append(f"  {label + ':':<14}{len(codes):>5}  {shown}".rstrip())
    lines.append(f"  {'Unchanged:':<14}{report.unchanged:>5}")
    if not report.issues:
        lines.append("")
        lines.append(
            "Loaded." if report.applied else "Preview only: nothing was changed. Add --apply to load it."
        )
    return "\n".join(lines)
