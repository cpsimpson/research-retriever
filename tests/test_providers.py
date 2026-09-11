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


def test_crossref_reference_extracts_title_from_apa_style_unstructured_citation() -> None:
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "unstructured": (
                            "Nielsen F. Å. (2011). A new evaluation of a word list for "
                            "sentiment analysis in microblogs. ESWC2011 Workshop on "
                            "“Making Sense of Microposts”: Big things come in small "
                            "packages (pp. 93–98). Retrieved from "
                            "http://arxiv.org/abs/1103.2903"
                        )
                    }
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert references[0].title == (
        "A new evaluation of a word list for sentiment analysis in microblogs"
    )
    assert references[0].publication_year == 2011
    assert references[0].authors[0].name == "F. Å. Nielsen"


def test_crossref_reference_splits_multi_author_unstructured_citation() -> None:
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "unstructured": (
                            "Endsley, M. R., Caldwell, B., Chiou, K. E., Cummings, L. M., "
                            "Gonzalez, C., Lee, D. J., et al. (2021). Human-AI Teaming: "
                            "State-of-the-Art and Research Needs. Washington, DC: The "
                            "National Academies Press."
                        )
                    }
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert [author.name for author in references[0].authors] == [
        "M. R. Endsley",
        "B. Caldwell",
        "K. E. Chiou",
        "L. M. Cummings",
        "C. Gonzalez",
        "D. J. Lee",
    ]


def test_crossref_reference_prefers_unstructured_title_over_stray_volume_title() -> None:
    """volume-title sometimes names the containing proceedings, not this work, when
    article-title is absent; the unstructured citation's own title is more reliable."""
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "volume-title": "IFAC-PapersOnLine",
                        "author": "Hu W. L.",
                        "year": "2016",
                        "unstructured": (
                            "Hu W. L., Akash K., Jain N., Reid T. (2016). Real-time sensing "
                            "of trust in human-machine interactions. IFAC-PapersOnLine, "
                            "49(32), 48–53. Elsevier B.V."
                        ),
                    }
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert references[0].title == "Real-time sensing of trust in human-machine interactions"
    assert [author.name for author in references[0].authors] == [
        "W. L. Hu",
        "K. Akash",
        "N. Jain",
        "T. Reid",
    ]


def test_crossref_reference_uses_volume_title_when_no_unstructured_text() -> None:
    client = FakeClient(
        {"message": {"reference": [{"volume-title": "A Whole Book", "year": "2019"}]}}
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert references[0].title == "A Whole Book"


def test_crossref_reference_keeps_lowercase_surname_particles() -> None:
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "unstructured": (
                            "Kohn S. C., de Visser E. J., Wiese E. (2021). Measurement of "
                            "trust in automation. Frontiers in Psychology, 12, 1–23."
                        )
                    }
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert [author.name for author in references[0].authors] == [
        "S. C. Kohn",
        "E. J. de Visser",
        "E. Wiese",
    ]


def test_crossref_reference_tolerates_comma_typo_between_initials() -> None:
    client = FakeClient(
        {
            "message": {
                "reference": [
                    {
                        "unstructured": (
                            "Cooke J, N. Cummings L. M. (2021). Some title. A journal, 1(1), 1."
                        )
                    }
                ]
            }
        }
    )
    references = CrossrefProvider("researcher@example.test", client=client).references(
        "10.1/source"
    )
    assert [author.name for author in references[0].authors] == [
        "J, N. Cooke",
        "L. M. Cummings",
    ]


def test_crossref_reference_author_split_does_not_swallow_next_surname() -> None:
    """A comma with no period anywhere nearby must not be treated as an initial
    separator, or it would truncate the following author's surname to one letter."""
    from research_retriever.providers.crossref import _parse_authors

    assert _parse_authors("Smith A, Jones B.") == ("B. Jones",)
