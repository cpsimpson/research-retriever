import json

import pytest

from research_retriever.references import OllamaReferenceParser, reference_section


class OllamaClient:
    def request_json(self, method, url, payload):
        assert method == "POST"
        assert url.endswith("/api/chat")
        assert "References" not in payload["messages"][1]["content"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "references": [
                            {
                                "raw": "Lovelace, A. (1843). Notes. doi:10.1/NOTES",
                                "title": "Notes",
                                "authors": ["Lovelace, A."],
                                "year": "1843",
                                "doi": "10.1/NOTES",
                            }
                        ]
                    }
                )
            }
        }


def test_reference_section_uses_last_bibliography_heading() -> None:
    text = "References\nmentioned in prose\n\nBody\n\nReferences\nLovelace, A. (1843). Notes."
    assert reference_section(text) == "Lovelace, A. (1843). Notes."


@pytest.mark.parametrize(
    "heading",
    ["References and Recommended Reading", "References & Recommended Reading:"],
)
def test_reference_section_accepts_recommended_reading_headings(heading) -> None:
    text = f"Body text\n\n{heading}\nLovelace, A. (1843). Notes."
    assert reference_section(text) == "Lovelace, A. (1843). Notes."


def test_reference_section_requires_a_heading() -> None:
    with pytest.raises(RuntimeError, match="heading"):
        reference_section("A document without a bibliography heading." * 3)


def test_ollama_parser_returns_conservative_structured_citations() -> None:
    parser = OllamaReferenceParser("model", client=OllamaClient())
    references = parser.parse("Body\n\nReferences\n" + "Lovelace citation " * 10)
    assert references[0].title == "Notes"
    assert references[0].year == 1843
    assert references[0].doi == "10.1/notes"
