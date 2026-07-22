from datetime import date

from research_retriever.analysis import PaperAnalysis
from research_retriever.models import Author, Origin, Paper, RelationshipType, WorkType
from research_retriever.obsidian import ObsidianWriter
from research_retriever.references import ExtractedReference
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


class VersionZotero(FakeZotero):
    def __init__(self):
        self.links = []

    def link_references(self, source, targets):
        self.links.append((source, list(targets)))


class CountingAnalyzer:
    def __init__(self):
        self.calls = 0

    def analyze(self, _paper, _interest, source_text=None):
        self.calls += 1
        return PaperAnalysis(summary="A daily summary.")


class PDFZotero(VersionZotero):
    def pdf_full_text(self, _key):
        return "Body\nReferences\nExtracted bibliography"

    def ensure_collection_path(self, _path):
        return "REFERENCES"

    def create_papers(self, papers, _collection):
        assert list(papers) == []
        return []


class PDFReferenceParser:
    def parse(self, _text):
        return [
            ExtractedReference(
                raw="Lovelace, A. (1843). Notes.",
                title="Notes",
                authors=("Lovelace, A.",),
                year=1843,
            ),
            ExtractedReference(raw="An unresolvable private manuscript"),
        ]


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

    papers, roundup_path = workflow.create_daily_roundup(date(2026, 7, 22), 1, 1.0, "My interests")
    assert len(papers) == 1
    assert analyzer.calls == 1
    assert roundup_path.exists()
    assert (tmp_path / "vault" / papers[0].obsidian_path).exists()


def test_reference_harvest_falls_back_to_attached_pdf_and_preserves_unresolved(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    manuscript = Paper(title="Draft", zotero_key="DRAFT123")
    cited = Paper(
        title="Notes",
        authors=[Author("Ada Lovelace")],
        publication_year=1843,
        zotero_key="CITED123",
    )
    store.upsert(manuscript)
    store.upsert(cited)
    zotero = PDFZotero()
    obsidian = ObsidianWriter(tmp_path / "vault", "Literature", "Roundups")
    workflow = ResearchWorkflow(
        store,
        zotero,
        obsidian=obsidian,
        reference_parser=PDFReferenceParser(),
    )

    result = workflow.harvest_references(manuscript)

    assert result.source == "attached PDF"
    assert result.already_present == 1
    assert result.unresolved == 1
    assert zotero.links == [("DRAFT123", ["CITED123"])]
    note = (tmp_path / "vault" / manuscript.obsidian_path).read_text()
    assert "Unresolved references from the attached PDF" in note
    assert "An unresolvable private manuscript" in note


def test_same_title_author_preprint_is_linked_to_publication_and_skipped_in_roundup(
    tmp_path,
) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    preprint = Paper(
        title="Why people trust AI?",
        authors=[Author("A. Researcher")],
        doi="10.1/preprint",
        work_type=WorkType.PREPRINT,
        origin=Origin.TOOL_ZOTERO,
        zotero_key="PREPRINT",
    )
    publication = Paper(
        title="Why people trust AI",
        authors=[Author("A Researcher"), Author("B Researcher")],
        doi="10.1/published",
        work_type=WorkType.JOURNAL_ARTICLE,
        origin=Origin.TOOL_ZOTERO,
        zotero_key="PUBLISHED",
    )
    store.upsert(preprint)
    store.upsert(publication)
    zotero = VersionZotero()
    workflow = ResearchWorkflow(store, zotero)

    versions = workflow.check_updated_versions(preprint)

    assert [paper.canonical_key for paper in versions] == [publication.canonical_key]
    assert store.relationships_from(preprint.canonical_key)[0].relationship == (
        RelationshipType.PREPRINT_OF
    )
    assert store.relationships_from(preprint.canonical_key)[0].verified is False
    assert store.relationships_from(publication.canonical_key)[0].relationship == (
        RelationshipType.VERSION_OF
    )
    assert ("PREPRINT", ["PUBLISHED"]) in zotero.links
    assert ("PUBLISHED", ["PREPRINT"]) in zotero.links
    assert [paper.canonical_key for paper in store.roundup_candidates(10, 0.0)] == [
        publication.canonical_key
    ]


def test_same_title_without_author_overlap_is_not_inferred_as_a_version(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    preprint = Paper(
        title="A common research title",
        authors=[Author("First Team")],
        doi="10.1/preprint",
        work_type=WorkType.PREPRINT,
    )
    publication = Paper(
        title="A common research title",
        authors=[Author("Different Team")],
        doi="10.1/published",
        work_type=WorkType.JOURNAL_ARTICLE,
    )
    store.upsert(preprint)
    store.upsert(publication)

    versions = ResearchWorkflow(store, VersionZotero()).check_updated_versions(preprint)

    assert versions == []
    assert store.relationships_from(preprint.canonical_key) == []


def test_local_reconciliation_links_existing_strong_pairs(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    preprint = Paper(
        title="A versioned study",
        authors=[Author("Same Author")],
        doi="10.1/preprint",
        work_type=WorkType.PREPRINT,
        zotero_key="PREPRINT",
    )
    publication = Paper(
        title="A versioned study",
        authors=[Author("Same Author")],
        doi="10.1/published",
        work_type=WorkType.JOURNAL_ARTICLE,
        zotero_key="PUBLISHED",
    )
    unrelated = Paper(
        title="A versioned study",
        authors=[Author("Other Author")],
        doi="10.1/unrelated",
        work_type=WorkType.JOURNAL_ARTICLE,
        zotero_key="UNRELATED",
    )
    for paper in (preprint, publication, unrelated):
        store.upsert(paper)
    zotero = VersionZotero()

    pairs = ResearchWorkflow(store, zotero).reconcile_local_versions()

    assert [(first.canonical_key, second.canonical_key) for first, second in pairs] == [
        (preprint.canonical_key, publication.canonical_key)
    ]
    assert ("PREPRINT", ["PUBLISHED"]) in zotero.links
