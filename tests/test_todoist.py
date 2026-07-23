from datetime import date

import pytest

from research_retriever.todoist import TodoistClient


class RecordingClient:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, payload):
        self.calls.append((method, url, payload))
        return {}


def test_daily_reminder_uses_quick_add_and_links_obsidian(tmp_path) -> None:
    vault = tmp_path / "Research Vault"
    roundup = vault / "Research Roundups" / "2026-08-01.md"
    client = RecordingClient()
    todoist = TodoistClient(
        "secret",
        "Read {{count}} papers from {{date}} {{obsidian_uri}} {{due}} #Reading",
        client=client,
    )

    todoist.create_roundup_reminder(date(2026, 8, 1), 6, vault, roundup)

    method, url, payload = client.calls[0]
    assert method == "POST"
    assert url.endswith("/api/v1/tasks/quick")
    assert "Read 6 papers from 2026-08-01" in payload["text"]
    assert (
        "obsidian://open?vault=Research%20Vault&file=Research%20Roundups/2026-08-01.md"
        in (payload["text"])
    )
    assert "2026-08-01 #Reading" in payload["text"]


def test_daily_reminder_requires_token(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="TODOIST_API_TOKEN"):
        TodoistClient("", "Reminder").create_roundup_reminder(
            date(2026, 8, 1), 1, tmp_path, tmp_path / "roundup.md"
        )
