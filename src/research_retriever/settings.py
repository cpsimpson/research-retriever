"""TOML configuration with environment-only secrets."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TopicSettings:
    id: str
    name: str
    query: str
    interest: str
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ZoteroSettings:
    library_type: str
    library_id: str
    api_key_env: str = "ZOTERO_API_KEY"
    inbox_collection: str = "Research Retriever/Inbox"
    references_collection: str = "Research Retriever/References"

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    email: str
    openalex_api_key_env: str = "OPENALEX_API_KEY"
    analysis_provider: str = "openai"
    analysis_api_key_env: str = "OPENAI_API_KEY"
    analysis_model: str = "gpt-5.6-luna"
    analysis_base_url: str = "http://127.0.0.1:11434"

    @property
    def openalex_api_key(self) -> str:
        return os.environ.get(self.openalex_api_key_env, "")

    @property
    def analysis_api_key(self) -> str:
        return os.environ.get(self.analysis_api_key_env, "")


@dataclass(frozen=True, slots=True)
class AppSettings:
    vault_path: Path
    state_path: Path
    notes_folder: str = "Literature Notes"
    roundup_folder: str = "Research Roundups"
    daily_limit: int = 8
    backlog_fraction: float = 0.4


@dataclass(frozen=True, slots=True)
class TodoistSettings:
    enabled: bool = False
    api_token_env: str = "TODOIST_API_TOKEN"
    daily_template: str = (
        "Review research roundup for {{date}} ({{count}} papers) {{obsidian_uri}} {{due}} #Reading"
    )

    @property
    def api_token(self) -> str:
        return os.environ.get(self.api_token_env, "")


@dataclass(frozen=True, slots=True)
class Settings:
    app: AppSettings
    zotero: ZoteroSettings
    providers: ProviderSettings
    todoist: TodoistSettings = field(default_factory=TodoistSettings)
    topics: tuple[TopicSettings, ...] = field(default_factory=tuple)


def default_config_path() -> Path:
    override = os.environ.get("RESEARCH_RETRIEVER_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/research-retriever/config.toml"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / (
        "research-retriever/config.toml"
    )


def default_state_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/research-retriever/catalog.sqlite3"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / (
        "research-retriever/catalog.sqlite3"
    )


def load_settings(path: Path | str | None = None) -> Settings:
    config_path = Path(path).expanduser() if path else default_config_path()
    with config_path.open("rb") as stream:
        data = tomllib.load(stream)
    app = data.get("app", {})
    providers = data.get("providers", {})
    zotero = data.get("zotero", {})
    todoist = data.get("todoist", {})
    return Settings(
        app=AppSettings(
            vault_path=Path(_required(app, "vault_path")).expanduser(),
            state_path=Path(app.get("state_path", default_state_path())).expanduser(),
            notes_folder=app.get("notes_folder", "Literature Notes"),
            roundup_folder=app.get("roundup_folder", "Research Roundups"),
            daily_limit=int(app.get("daily_limit", 8)),
            backlog_fraction=float(app.get("backlog_fraction", 0.4)),
        ),
        zotero=ZoteroSettings(
            library_type=zotero.get("library_type", "user"),
            library_id=str(_required(zotero, "library_id")),
            api_key_env=zotero.get("api_key_env", "ZOTERO_API_KEY"),
            inbox_collection=zotero.get("inbox_collection", "Research Retriever/Inbox"),
            references_collection=zotero.get(
                "references_collection", "Research Retriever/References"
            ),
        ),
        providers=ProviderSettings(
            email=_required(providers, "email"),
            openalex_api_key_env=providers.get("openalex_api_key_env", "OPENALEX_API_KEY"),
            analysis_provider=providers.get("analysis_provider", "openai"),
            analysis_api_key_env=providers.get("analysis_api_key_env", "OPENAI_API_KEY"),
            analysis_model=providers.get("analysis_model", "gpt-5.6-luna"),
            analysis_base_url=providers.get("analysis_base_url", "http://127.0.0.1:11434"),
        ),
        todoist=TodoistSettings(
            enabled=bool(todoist.get("enabled", False)),
            api_token_env=todoist.get("api_token_env", "TODOIST_API_TOKEN"),
            daily_template=todoist.get(
                "daily_template",
                "Review research roundup for {{date}} ({{count}} papers) "
                "{{obsidian_uri}} {{due}} #Reading",
            ),
        ),
        topics=tuple(
            TopicSettings(
                id=_required(topic, "id"),
                name=_required(topic, "name"),
                query=_required(topic, "query"),
                interest=topic.get("interest", topic.get("query", "")),
                include_terms=tuple(topic.get("include_terms", [])),
                exclude_terms=tuple(topic.get("exclude_terms", [])),
            )
            for topic in data.get("topics", [])
        ),
    )


def starter_config(vault_path: Path, library_id: str, email: str) -> str:
    state = default_state_path()
    todoist_template = (
        "Review research roundup for {{date}} ({{count}} papers) {{obsidian_uri}} {{due}} #Reading"
    )
    return f'''# Secrets are read from ZOTERO_API_KEY, OPENALEX_API_KEY, and TODOIST_API_TOKEN.
[app]
vault_path = "{vault_path.expanduser()}"
state_path = "{state}"
notes_folder = "Literature Notes"
roundup_folder = "Research Roundups"
daily_limit = 8
backlog_fraction = 0.4

[zotero]
library_type = "user"
library_id = "{library_id}"
api_key_env = "ZOTERO_API_KEY"
inbox_collection = "Research Retriever/Inbox"
references_collection = "Research Retriever/References"

[providers]
email = "{email}"
openalex_api_key_env = "OPENALEX_API_KEY"
analysis_provider = "openai"
analysis_api_key_env = "OPENAI_API_KEY"
analysis_model = "gpt-5.6-luna"
analysis_base_url = "http://127.0.0.1:11434"

[todoist]
enabled = false
api_token_env = "TODOIST_API_TOKEN"
daily_template = "{todoist_template}"

[[topics]]
id = "example-topic"
name = "Replace with a research topic"
query = "Replace with a detailed natural-language description of the research topic"
interest = "Explain why papers on this topic are useful to your research"
include_terms = []
exclude_terms = []
'''


def _required(mapping: dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required configuration value: {key}")
    return value
