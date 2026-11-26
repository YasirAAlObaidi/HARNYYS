"""The `yyai` command: the product sheet, and the staff users of the web app.

    yyai products import products.xlsx            # preview: what would be added, changed, switched off
    yyai products import products.xlsx --apply    # load it
    yyai products export products.xlsx            # the current table, in the same layout

    yyai users add NAME --role admin|sales|viewer [--display-name "Full Name"]
    yyai users list
    yyai users reset NAME                         # new password and new 2FA secret
    yyai users disable NAME                       # also logs them out everywhere
    yyai users enable NAME

`users add` and `users reset` ask for the password (twice) and print the 2FA secret, the otpauth link and a QR
code to scan with an authenticator app. With no terminal (a script), the password is read from one line of input.

On a client box, inside Docker (the client folder is mounted at /config):

    docker compose -f deploy/compose.yaml run --rm server yyai products import /config/products.xlsx --apply
    docker compose -f deploy/compose.yaml run --rm server yyai users add yasir --role admin

Like main.py and worker.py, this is a composition root: it reads the config and wires everything with
yyai.bootstrap, then calls one workflow.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import sys
from pathlib import Path

import segno

from yyai.bootstrap import build
from yyai.core.config import load_config
from yyai.core.errors import Conflict, InvalidFile
from yyai.core.logging import configure_logging
from yyai.core.types import NewStaffUser, ProductImportReport, StaffRole
from yyai.workflows.container import Workflows
from yyai.workflows.products import ProductSheetWorkflow

EXIT_OK = 0
EXIT_SHEET_PROBLEMS = 1
EXIT_UNREADABLE = 2
EXIT_USER_PROBLEM = 3
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

    users = commands.add_parser("users", help="staff logins for the web app")
    user_actions = users.add_subparsers(dest="action", required=True)
    add = user_actions.add_parser("add", help="create a staff user and print their 2FA enrolment")
    add.add_argument("name", help="the username they log in with (letters, digits, . - _)")
    add.add_argument("--role", required=True, choices=[role.value for role in StaffRole])
    add.add_argument("--display-name", help="the name shown in the app, e.g. 'Yasir Ali'")
    user_actions.add_parser("list", help="list staff users")
    reset = user_actions.add_parser("reset", help="set a new password and a new 2FA secret")
    reset.add_argument("name")
    disable = user_actions.add_parser("disable", help="stop a user logging in (ends their sessions)")
    disable.add_argument("name")
    enable = user_actions.add_parser("enable", help="let a disabled user log in again")
    enable.add_argument("name")
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    workflows = build(load_config())
    try:
        if args.command == "users":
            return await _users(workflows, args)
        if args.action == "import":
            return await _import(workflows.products, args)
        data = await workflows.products.export_sheet()
        args.file.write_bytes(data)
        print(f"Wrote {args.file}")
        return EXIT_OK
    finally:
        await workflows.aclose()


# --- users -----------------------------------------------------------------------------------------------------


async def _users(workflows: Workflows, args: argparse.Namespace) -> int:
    staff = workflows.staff
    try:
        if args.action == "list":
            for user in await staff.list_users():
                last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"
                state = "" if user.active else "  (disabled)"
                print(f"{user.username:<20} {user.role.value:<7} last login: {last}{state}")
            return EXIT_OK
        if args.action in ("disable", "enable"):
            if not await staff.set_active(args.name, args.action == "enable"):
                print(f"No staff user called {args.name!r}", file=sys.stderr)
                return EXIT_USER_PROBLEM
            print(f"{args.name}: {args.action}d")
            return EXIT_OK
        password = read_password()
        if args.action == "add":
            created = await staff.add_user(args.name, StaffRole(args.role), password, args.display_name)
        else:
            found = await staff.reset_user(args.name, password)
            if found is None:
                print(f"No staff user called {args.name!r}", file=sys.stderr)
                return EXIT_USER_PROBLEM
            created = found
    except (ValueError, Conflict) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USER_PROBLEM
    print(format_enrolment(created, qr=sys.stdout.isatty()))
    return EXIT_OK


def read_password() -> str:
    """Ask twice on a terminal. From a script, read one line of standard input. Raises ValueError on a mismatch."""
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password (at least 12 characters): ")
    if getpass.getpass("Same password again: ") != first:
        raise ValueError("The two passwords are not the same. Nothing was changed.")
    return first


def format_enrolment(created: NewStaffUser, *, qr: bool) -> str:
    """What to show once, so the person can add the account to an authenticator app."""
    secret = " ".join(created.totp_secret[i : i + 4] for i in range(0, len(created.totp_secret), 4))
    lines = [
        f"Staff user {created.user.username!r} ({created.user.role.value}) is ready.",
        "",
        "Two-factor login: open an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password,",
        "Authy...), add an account, and scan the QR code below, or type the setup key by hand.",
        "",
        f"  Setup key:  {secret}",
        f"  Link:       {created.totp_uri}",
        "",
    ]
    if qr:
        drawing = io.StringIO()
        segno.make(created.totp_uri, error="m").terminal(out=drawing, compact=True)
        lines.append(drawing.getvalue())
    lines.append("This is shown only now. Lost it? Run `yyai users reset` for a new password and key.")
    return "\n".join(lines)


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
