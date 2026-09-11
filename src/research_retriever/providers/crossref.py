"""Crossref metadata and publication-version relationship adapter."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from research_retriever.http import JsonHttpClient
from research_retriever.models import (
    Author,
    Origin,
    Paper,
    PaperRelationship,
    RecordStatus,
    RelationshipType,
    ReviewStatus,
    VenueSignals,
    WorkType,
    normalize_doi,
)

RELATIONSHIP_MAP = {
    "is-preprint-of": RelationshipType.PREPRINT_OF,
    "is-preprintof": RelationshipType.PREPRINT_OF,
    "is-version-of": RelationshipType.VERSION_OF,
    "is-versionof": RelationshipType.VERSION_OF,
    "is-replaced-by": RelationshipType.REPLACES,
    "is-replacedby": RelationshipType.REPLACES,
    "has-version": RelationshipType.VERSION_OF,
    "has-preprint": RelationshipType.PREPRINT_OF,
}


class CrossrefProvider:
    base_url = "https://api.crossref.org"

    def __init__(self, mailto: str, client: JsonHttpClient | None = None) -> None:
        if not mailto:
            raise ValueError("Crossref polite-pool access requires an email address")
        self.mailto = mailto
        self.client = client or JsonHttpClient(
            user_agent=f"research-retriever/0.1 (mailto:{mailto})"
        )

    def work(self, doi: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(normalize_doi(doi), safe="")
        response = self.client.get(f"{self.base_url}/works/{encoded}", {"mailto": self.mailto})
        return response["message"]

    def version_relationships(self, doi: str) -> list[PaperRelationship]:
        source_key = f"doi:{normalize_doi(doi)}"
        message = self.work(doi)
        output: list[PaperRelationship] = []
        for raw_name, values in (message.get("relation") or {}).items():
            name = raw_name.lower().replace("_", "-")
            relationship = RELATIONSHIP_MAP.get(name)
            if relationship is None:
                continue
            for value in _as_list(values):
                target = value.get("id") if isinstance(value, dict) else value
                if not target:
                    continue
                target_key = f"doi:{normalize_doi(str(target))}"
                if name.startswith("has-"):
                    output.append(
                        PaperRelationship(
                            source_key=target_key,
                            target_key=source_key,
                            relationship=relationship,
                            evidence_source="Crossref relation metadata",
                            verified=True,
                        )
                    )
                else:
                    output.append(
                        PaperRelationship(
                            source_key=source_key,
                            target_key=target_key,
                            relationship=relationship,
                            evidence_source="Crossref relation metadata",
                            verified=True,
                        )
                    )
        return output

    def references(self, doi: str) -> list[Paper]:
        message = self.work(doi)
        output: list[Paper] = []
        for index, reference in enumerate(message.get("reference") or [], 1):
            raw_doi = reference.get("DOI") or reference.get("doi")
            unstructured = reference.get("unstructured")
            parsed = _parse_unstructured(unstructured) if unstructured else _ParsedCitation()
            title = (
                reference.get("article-title")
                or parsed.title
                or reference.get("volume-title")
                or reference.get("series-title")
                or f"Unresolved reference {index} from {normalize_doi(doi)}"
            )
            raw_year = str(reference.get("year") or parsed.year or "")
            raw_authors = parsed.authors or (
                (str(reference["author"]),) if reference.get("author") else ()
            )
            output.append(
                Paper(
                    title=str(title)[:500],
                    authors=[Author(name) for name in raw_authors],
                    publication_year=int(raw_year) if raw_year.isdigit() else None,
                    doi=normalize_doi(str(raw_doi)) if raw_doi else None,
                    url=parsed.url,
                    work_type=WorkType.JOURNAL_ARTICLE,
                    review_status=ReviewStatus.UNKNOWN,
                    record_status=RecordStatus.UNKNOWN,
                    origin=Origin.CITED_REFERENCE,
                    venue=VenueSignals(
                        name=reference.get("journal-title"), source="Crossref reference deposit"
                    ),
                    discovered_by="Crossref reference deposit",
                    metadata={"crossref_reference": reference, "citing_doi": normalize_doi(doi)},
                )
            )
        return output


def _as_list(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else [value]


UNSTRUCTURED_CITATION_PATTERN = re.compile(
    r"^(?P<author>.*?)\(\s*(?P<year>\d{4})\w?\s*\)\.\s*(?P<title>.+?)\.(?:\s|$)"
)
URL_PATTERN = re.compile(r"https?://\S+")
SURNAME_FIRST_PATTERN = re.compile(r"^(?P<surname>\S+),?\s+(?P<initials>(?:\S+\.\s*)+)$")
AUTHOR_LIST_TOKEN_PATTERN = re.compile(
    r"(?P<surname>[A-ZÀ-Þ][A-Za-zÀ-ÿ'-]+),?\s+(?P<initials>(?:[A-ZÀ-Þ]\.\s*)+)"
)


@dataclass(slots=True, frozen=True)
class _ParsedCitation:
    title: str | None = None
    year: str | None = None
    authors: tuple[str, ...] = ()
    url: str | None = None


def _parse_unstructured(citation: str) -> _ParsedCitation:
    """Recover title/year/authors/url from an APA-style "Author (Year). Title. Source" citation."""
    url_match = URL_PATTERN.search(citation)
    url = url_match.group(0).rstrip(").,;") if url_match else None
    match = UNSTRUCTURED_CITATION_PATTERN.match(citation.strip())
    if not match:
        return _ParsedCitation(title=citation, url=url)
    return _ParsedCitation(
        title=match.group("title").strip(),
        year=match.group("year"),
        authors=_parse_authors(match.group("author").strip()),
        url=url,
    )


def _parse_authors(text: str) -> tuple[str, ...]:
    """Extract "Surname, I. I." entries from an author list, reordered to "I. I. Surname"."""
    matches = [
        f"{match.group('initials').strip()} {match.group('surname')}"
        for match in AUTHOR_LIST_TOKEN_PATTERN.finditer(text)
    ]
    if matches:
        return tuple(matches)
    reordered = _reorder_surname_first(text)
    return (reordered,) if reordered else ()


def _reorder_surname_first(author: str) -> str:
    """Convert citation-style "Surname F. M." to this codebase's "F. M. Surname" convention."""
    match = SURNAME_FIRST_PATTERN.match(author)
    if not match:
        return author
    return f"{match.group('initials').strip()} {match.group('surname')}"
