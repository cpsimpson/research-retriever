"""Command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from research_retriever import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-retriever",
        description="Discover and organize research papers with Zotero and Obsidian.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Create a starter configuration file.")
    subparsers.add_parser("doctor", help="Check configuration and service connectivity.")
    subparsers.add_parser("sync", help="Synchronize Zotero, the catalog, and Obsidian notes.")
    subparsers.add_parser("discover", help="Find papers for configured research topics.")
    subparsers.add_parser("daily", help="Create today's reading round-up.")
    subparsers.add_parser("harvest-references", help="Import references cited by a paper.")

    status = subparsers.add_parser("status", help="Set the reading status of a paper.")
    status.add_argument("paper", help="DOI, Zotero item key, or catalog identifier.")
    status.add_argument("value", choices=("unread", "queued", "reading", "read", "skipped"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    parser.error(f"The {args.command!r} command has not been implemented yet")
    return 2

