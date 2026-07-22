from research_retriever.models import Author, Paper, WorkType, normalize_doi


def test_doi_is_normalized_for_stable_identity() -> None:
    paper = Paper(title="Example", doi="https://doi.org/10.1234/ABC.")
    assert normalize_doi(paper.doi) == "10.1234/abc"
    assert paper.canonical_key == "doi:10.1234/abc"


def test_title_identity_is_stable_without_external_identifier() -> None:
    first = Paper(title="A Paper: About Things", authors=[Author("Ada Lovelace")], publication_year=2025)
    second = Paper(title="A paper about things", authors=[Author("Ada Lovelace")], publication_year=2025)
    assert first.canonical_key == second.canonical_key


def test_model_json_round_trip() -> None:
    paper = Paper(title="Example", work_type=WorkType.PREPRINT, authors=[Author("A. Author")])
    restored = Paper.from_json(paper.to_json())
    assert restored == paper

