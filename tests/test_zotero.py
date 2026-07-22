from research_retriever.models import Origin, Paper, ReadingStatus, WorkType
from research_retriever.settings import ZoteroSettings
from research_retriever.zotero import ZoteroClient, paper_from_zotero


def test_manual_zotero_item_is_classified_and_read_status_is_imported() -> None:
    paper = paper_from_zotero(
        {
            "key": "ABCD1234",
            "version": 12,
            "data": {
                "itemType": "preprint",
                "title": "An early paper",
                "DOI": "10.1/EARLY",
                "date": "2025-01-01",
                "tags": [{"tag": "rr:reading"}],
                "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
            },
        }
    )
    assert paper.origin == Origin.MANUAL_ZOTERO
    assert paper.added_by_tool is False
    assert paper.work_type == WorkType.PREPRINT
    assert paper.reading_status == ReadingStatus.READING
    assert paper.zotero_key == "ABCD1234"


class TemplateClient:
    def get(self, *_args, **_kwargs):
        return {
            "itemType": "journalArticle",
            "title": "",
            "creators": [],
            "abstractNote": "",
            "date": "",
            "publicationTitle": "",
            "DOI": "",
            "url": "",
            "tags": [],
            "collections": [],
            "relations": {},
        }


def test_zotero_payload_marks_tool_provenance(monkeypatch) -> None:
    monkeypatch.setenv("ZOTERO_API_KEY", "secret")
    client = ZoteroClient(ZoteroSettings("user", "123"), client=TemplateClient())
    payload = client.paper_payload(
        Paper(title="A result", doi="10.1/result", work_type=WorkType.JOURNAL_ARTICLE)
    )
    assert {tag["tag"] for tag in payload["tags"]} == {
        "rr:managed",
        "rr:type:journal_article",
    }
    assert payload["DOI"] == "10.1/result"
