from datetime import date

from research_retriever.analysis import PaperAnalysis
from research_retriever.obsidian import ObsidianWriter
from research_retriever.settings import ZoteroSettings
from research_retriever.store import PaperStore
from research_retriever.workflows import ResearchWorkflow


class FakeZotero:
    settings = ZoteroSettings("user", "123")

    def list_top_items(self, _since=None):
        return [
            {
                "key": "ABCD1234",
                "version": 1,
                "data": {
                    "key": "ABCD1234",
                    "version": 1,
                    "itemType": "journalArticle",
                    "title": "An unread library paper",
                    "date": "2024",
                    "tags": [],
                    "creators": [],
                },
            }
        ]

    def set_reading_status(self, _key, _status):
        return None


class CountingAnalyzer:
    def __init__(self):
        self.calls = 0

    def analyze(self, _paper, _interest, source_text=None):
        self.calls += 1
        return PaperAnalysis(summary="A daily summary.")


def test_initial_library_is_cataloged_then_processed_gradually(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZOTERO_API_KEY", "secret")
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    analyzer = CountingAnalyzer()
    obsidian = ObsidianWriter(tmp_path / "vault", "Literature", "Roundups")
    workflow = ResearchWorkflow(store, FakeZotero(), analyzer=analyzer, obsidian=obsidian)

    result = workflow.sync_zotero()
    assert result.initial_import is True
    assert workflow.process_new_zotero_items(result, "My interests") == []
    assert analyzer.calls == 0

    papers, roundup_path = workflow.create_daily_roundup(
        date(2026, 7, 22), 1, 1.0, "My interests"
    )
    assert len(papers) == 1
    assert analyzer.calls == 1
    assert roundup_path.exists()
    assert (tmp_path / "vault" / papers[0].obsidian_path).exists()

