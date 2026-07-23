"""Optional Todoist integration for daily research roundups."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import quote

from research_retriever.http import JsonHttpClient


class TodoistClient:
    endpoint = "https://api.todoist.com/api/v1/tasks/quick"

    def __init__(
        self,
        token: str,
        template: str,
        client: JsonHttpClient | None = None,
    ) -> None:
        self.token = token
        self.template = template
        self.client = client or JsonHttpClient(
            user_agent="research-retriever/0.1",
            default_headers={"Authorization": f"Bearer {token}"},
        )

    def create_roundup_reminder(
        self,
        roundup_date: date,
        paper_count: int,
        vault_path: Path,
        roundup_path: Path,
    ) -> None:
        if not self.token:
            raise RuntimeError("Set the Todoist token in TODOIST_API_TOKEN")
        relative_path = roundup_path.relative_to(vault_path)
        variables = {
            "date": roundup_date.isoformat(),
            "due": "today" if roundup_date == date.today() else roundup_date.isoformat(),
            "count": str(paper_count),
            "obsidian_uri": _obsidian_uri(vault_path, relative_path),
            "roundup_path": str(roundup_path),
        }
        text = _render(self.template, variables)
        if not text:
            raise RuntimeError("The Todoist daily reminder template rendered as empty")
        self.client.request_json("POST", self.endpoint, {"text": text})


def _render(template: str, variables: dict[str, str]) -> str:
    output = template
    for key, value in variables.items():
        output = output.replace("{{" + key + "}}", value)
    return " ".join(output.split())


def _obsidian_uri(vault_path: Path, relative_path: Path) -> str:
    vault = quote(vault_path.name, safe="")
    file_path = quote(relative_path.as_posix(), safe="/")
    return f"obsidian://open?vault={vault}&file={file_path}"
