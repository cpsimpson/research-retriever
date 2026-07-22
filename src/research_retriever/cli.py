"""Command-line interface for local research workflows."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from research_retriever import __version__
from research_retriever.analysis import OpenAIAnalyzer, PendingAnalyzer
from research_retriever.models import ReadingStatus
from research_retriever.obsidian import ObsidianWriter
from research_retriever.providers import CrossrefProvider, OpenAlexProvider
from research_retriever.settings import (
    Settings,
    default_config_path,
    load_settings,
    starter_config,
)
from research_retriever.store import PaperStore
from research_retriever.workflows import ResearchWorkflow
from research_retriever.zotero import ZoteroClient


@dataclass(slots=True)
class Runtime:
    settings: Settings
    store: PaperStore
    zotero: ZoteroClient
    workflow: ResearchWorkflow
    obsidian: ObsidianWriter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-retriever",
        description="Discover and organize research papers with Zotero and Obsidian.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="TOML configuration path (defaults to the platform configuration directory).",
    )
    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="Create a starter configuration file.")
    init.add_argument("--vault", type=Path, help="Path to the Obsidian vault.")
    init.add_argument("--zotero-library-id", help="Numeric Zotero user or group library ID.")
    init.add_argument("--email", help="Contact email used for polite scholarly API access.")
    init.add_argument("--force", action="store_true", help="Replace an existing configuration.")

    subparsers.add_parser("doctor", help="Check configuration and service connectivity.")
    sync = subparsers.add_parser("sync", help="Import changes from Zotero and process new items.")
    sync.add_argument("--full", action="store_true", help="Ignore the saved Zotero sync version.")

    discover = subparsers.add_parser("discover", help="Find papers for configured research topics.")
    discover.add_argument("--topic", action="append", help="Topic ID to run; may be repeated.")
    discover.add_argument("--limit", type=int, default=10, help="Maximum results per topic.")

    daily = subparsers.add_parser("daily", help="Create a daily reading round-up.")
    daily.add_argument("--date", type=date.fromisoformat, default=None, help="Date in YYYY-MM-DD.")
    daily.add_argument(
        "--limit", type=int, default=None, help="Override the configured paper count."
    )

    harvest = subparsers.add_parser(
        "harvest-references", help="Import references cited by a paper."
    )
    harvest.add_argument("paper", help="DOI, Zotero item key, or catalog identifier.")

    analyze = subparsers.add_parser(
        "analyze", help="Analyze one cataloged paper and write its note."
    )
    analyze.add_argument("paper", help="DOI, Zotero item key, or catalog identifier.")

    versions = subparsers.add_parser(
        "check-versions", help="Check whether another publication version exists."
    )
    versions.add_argument("paper", help="DOI, Zotero item key, or catalog identifier.")

    status = subparsers.add_parser("status", help="Set the reading status of a paper.")
    status.add_argument("paper", help="DOI, Zotero item key, or catalog identifier.")
    status.add_argument("value", choices=tuple(status.value for status in ReadingStatus))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "init":
            return _init(args)
        runtime = _runtime(args.config)
        handlers = {
            "doctor": _doctor,
            "sync": _sync,
            "discover": _discover,
            "daily": _daily,
            "harvest-references": _harvest_references,
            "analyze": _analyze,
            "check-versions": _check_versions,
            "status": _status,
        }
        return handlers[args.command](runtime, args)
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _runtime(config_path: Path | None) -> Runtime:
    settings = load_settings(config_path)
    store = PaperStore(settings.app.state_path)
    store.initialize()
    zotero = ZoteroClient(settings.zotero)
    openalex = (
        OpenAlexProvider(
            settings.providers.openalex_api_key,
            settings.providers.email,
        )
        if settings.providers.openalex_api_key
        else None
    )
    crossref = CrossrefProvider(settings.providers.email)
    if settings.providers.analysis_provider == "openai" and settings.providers.analysis_api_key:
        analyzer = OpenAIAnalyzer(
            settings.providers.analysis_api_key,
            settings.providers.analysis_model,
        )
    else:
        analyzer = PendingAnalyzer()
    obsidian = ObsidianWriter(
        settings.app.vault_path,
        settings.app.notes_folder,
        settings.app.roundup_folder,
    )
    workflow = ResearchWorkflow(store, zotero, openalex, crossref, analyzer, obsidian)
    return Runtime(settings, store, zotero, workflow, obsidian)


def _init(args: argparse.Namespace) -> int:
    path = args.config or default_config_path()
    if path.exists() and not args.force:
        raise ValueError(f"Configuration already exists at {path}; use --force to replace it")
    vault = args.vault or Path(input("Obsidian vault path: ").strip())
    library_id = args.zotero_library_id or input("Zotero library ID: ").strip()
    email = args.email or input("Email for scholarly API requests: ").strip()
    if not vault or not library_id or not email:
        raise ValueError("Vault path, Zotero library ID, and email are required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(starter_config(vault, library_id, email), encoding="utf-8")
    print(f"Created {path}")
    print("Next: edit the topic profile and set ZOTERO_API_KEY and OPENALEX_API_KEY.")
    return 0


def _doctor(runtime: Runtime, _args: argparse.Namespace) -> int:
    problems: list[str] = []
    if not runtime.settings.app.vault_path.is_dir():
        problems.append(f"Obsidian vault does not exist: {runtime.settings.app.vault_path}")
    if not runtime.settings.providers.openalex_api_key:
        problems.append(
            f"{runtime.settings.providers.openalex_api_key_env} is unset; discovery is unavailable"
        )
    try:
        key = runtime.zotero.validate_key()
        print(f"Zotero key: valid for user {key.get('userID', 'unknown')}")
    except Exception as exc:
        problems.append(f"Zotero connection failed: {exc}")
    if not runtime.settings.providers.analysis_api_key:
        print("Analysis provider: disabled; notes will show analysis pending")
    else:
        print(f"Analysis provider: {runtime.settings.providers.analysis_provider}")
    if problems:
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Configuration is ready.")
    return 0


def _sync(runtime: Runtime, args: argparse.Namespace) -> int:
    result = runtime.workflow.sync_zotero(incremental=not args.full)
    interest = _combined_interest(runtime.settings)
    processed = runtime.workflow.process_new_zotero_items(result, interest)
    print(
        f"Imported {result.imported} Zotero item(s): {result.manual} manual and "
        f"{result.tool_managed} tool-managed."
    )
    if result.initial_import:
        print(
            "Initial backlog cataloged without bulk analysis; daily round-ups "
            "will process it gradually."
        )
    else:
        print(f"Processed {len(processed)} new or changed item(s) into the note workflow.")
    return 0


def _discover(runtime: Runtime, args: argparse.Namespace) -> int:
    if runtime.workflow.openalex is None:
        raise RuntimeError("Set OPENALEX_API_KEY before running discovery")
    requested = set(args.topic or [])
    topics = [topic for topic in runtime.settings.topics if not requested or topic.id in requested]
    missing = requested - {topic.id for topic in topics}
    if missing:
        raise ValueError(f"Unknown topic ID(s): {', '.join(sorted(missing))}")
    total = 0
    for topic in topics:
        papers = runtime.workflow.discover_topic(topic, args.limit)
        total += len(papers)
        print(f"{topic.name}: {len(papers)} paper(s)")
    print(f"Discovery completed with {total} matching paper(s).")
    return 0


def _daily(runtime: Runtime, args: argparse.Namespace) -> int:
    roundup_date = args.date or date.today()
    limit = args.limit or runtime.settings.app.daily_limit
    papers, path = runtime.workflow.create_daily_roundup(
        roundup_date,
        limit,
        runtime.settings.app.backlog_fraction,
        _combined_interest(runtime.settings),
    )
    print(f"Created a {len(papers)}-paper round-up at {path}")
    return 0


def _harvest_references(runtime: Runtime, args: argparse.Namespace) -> int:
    paper = _paper(runtime, args.paper)
    if not paper.external_ids.get("openalex"):
        paper = runtime.workflow.analyze_and_write(paper, _combined_interest(runtime.settings))
    result = runtime.workflow.harvest_references(paper)
    print(
        f"Retrieved {result.retrieved} unique reference(s); added {result.created} to Zotero "
        f"and linked {result.already_present} existing item(s)."
    )
    return 0


def _analyze(runtime: Runtime, args: argparse.Namespace) -> int:
    paper = runtime.workflow.analyze_and_write(
        _paper(runtime, args.paper), _combined_interest(runtime.settings), force=True
    )
    print(f"Updated note for {paper.title}: {paper.obsidian_path}")
    return 0


def _check_versions(runtime: Runtime, args: argparse.Namespace) -> int:
    paper = _paper(runtime, args.paper)
    versions = runtime.workflow.check_updated_versions(paper)
    runtime.workflow.write_note(paper)
    print(f"Found {len(versions)} related publication version(s).")
    return 0


def _status(runtime: Runtime, args: argparse.Namespace) -> int:
    status = ReadingStatus(args.value)
    paper = runtime.store.set_reading_status(_paper(runtime, args.paper).canonical_key, status)
    if paper.zotero_key:
        runtime.zotero.set_reading_status(paper.zotero_key, status)
    runtime.workflow.write_note(paper, reconcile_status=False)
    print(f"Marked {paper.title} as {status.value}.")
    return 0


def _paper(runtime: Runtime, identifier: str):
    paper = runtime.store.get(identifier)
    if paper is None and identifier.lower().startswith("10."):
        paper = runtime.store.get(f"doi:{identifier.lower()}")
    if paper is None:
        raise KeyError(f"Paper not found: {identifier}")
    return paper


def _combined_interest(settings: Settings) -> str:
    return "\n".join(f"- {topic.name}: {topic.interest}" for topic in settings.topics)
