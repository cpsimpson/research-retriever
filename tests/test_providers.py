from research_retriever.models import RecordStatus, ReviewStatus, WorkType
from research_retriever.providers.crossref import CrossrefProvider
from research_retriever.providers.openalex import OpenAlexProvider


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_openalex_parser_classifies_preprint_and_rebuilds_abstract() -> None:
    work = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1/preprint",
        "display_name": "An early result",
        "type": "preprint",
        "publication_year": 2026,
        "abstract_inverted_index": {"Useful": [0], "result": [2], "early": [1]},
        "authorships": [{"author": {"display_name": "A. Author"}}],
        "is_retracted": False,
        "primary_location": {"landing_page_url": "https://example.test/preprint"},
    }
    paper = OpenAlexProvider.parse_work(work, {"type": "repository", "display_name": "A server"})
    assert paper.work_type == WorkType.PREPRINT
    assert paper.review_status == ReviewStatus.NOT_PEER_REVIEWED
    assert paper.record_status == RecordStatus.ACTIVE
    assert paper.abstract == "Useful early result"
    assert paper.external_ids["openalex"] == "W123"


def test_openalex_parser_exposes_venue_signals() -> None:
    paper = OpenAlexProvider.parse_work(
        {"display_name": "Published result", "type": "article", "is_retracted": False},
        {
            "type": "journal",
            "display_name": "Journal of Examples",
            "is_in_doaj": True,
            "summary_stats": {"h_index": 42, "2yr_mean_citedness": 3.5},
        },
    )
    assert paper.work_type == WorkType.JOURNAL_ARTICLE
    assert paper.review_status == ReviewStatus.LIKELY_PEER_REVIEWED
    assert paper.venue.h_index == 42
    assert paper.venue.is_in_doaj is True


def test_openalex_discovery_treats_question_punctuation_as_prose() -> None:
    client = FakeClient({"results": []})
    provider = OpenAlexProvider("secret", client=client)

    provider.discover("How do people perceive AI? What explains it?", limit=10)

    params = client.calls[0][0][1]
    assert params["search"] == "How do people perceive AI What explains it"
    assert "mailto" not in params


def test_crossref_version_relationships_support_preprint_links() -> None:
    client = FakeClient(
        {"message": {"relation": {"is-preprint-of": [{"id": "10.1/PUBLISHED", "id-type": "doi"}]}}}
    )
    provider = CrossrefProvider("researcher@example.test", client=client)
    relationships = provider.version_relationships("10.1/preprint")
    assert len(relationships) == 1
    assert relationships[0].source_key == "doi:10.1/preprint"
    assert relationships[0].target_key == "doi:10.1/published"
    assert relationships[0].verified is True


def test_crossref_reference_fallback_preserves_unstructured_citations() -> None:
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "DOI": "10.2/REFERENCE",
                        "article-title": "A cited paper",
                        "author": "Author, A.",
                        "year": "2020",
                    },
                    {"unstructured": "B. Author. An older result. 1999."},
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert len(references) == 2
    assert references[0].doi == "10.2/reference"
    assert references[0].publication_year == 2020
    assert references[1].title.startswith("B. Author")
