"""OpenAlex discovery, citation graph, and venue-signal adapter."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Any

from research_retriever.http import JsonHttpClient
from research_retriever.models import (
    Author,
    Origin,
    Paper,
    RecordStatus,
    ReviewStatus,
    VenueSignals,
    WorkType,
    normalize_doi,
)


class OpenAlexProvider:
    base_url = "https://api.openalex.org"

    def __init__(self, api_key: str, client: JsonHttpClient | None = None) -> None:
        if not api_key:
            raise ValueError("OpenAlex requires an API key")
        self.api_key = api_key
        self.client = client or JsonHttpClient(user_agent="research-retriever/0.1")
        self._source_cache: dict[str, dict[str, Any]] = {}

    def discover(self, query: str, limit: int = 25) -> list[Paper]:
        response = self.client.get(
            f"{self.base_url}/works",
            {
                "search": _natural_language_search(query),
                "per_page": min(limit, 100),
                "sort": "relevance_score:desc",
                "api_key": self.api_key,
            },
        )
        return [
            self.parse_work(item, self._source_for(item)) for item in response.get("results", [])
        ]

    def get_work(self, identifier: str) -> Paper:
        encoded = urllib.parse.quote(identifier, safe="")
        response = self.client.get(
            f"{self.base_url}/works/{encoded}",
            {"api_key": self.api_key},
        )
        return self.parse_work(response, self._source_for(response))

    def get_work_by_doi(self, doi: str) -> Paper:
        return self.get_work(f"https://doi.org/{doi}")

    def references(self, paper: Paper) -> list[Paper]:
        openalex_id = paper.external_ids.get("openalex")
        if not openalex_id:
            raise ValueError("Paper has no OpenAlex identifier")
        raw = self.client.get(
            f"{self.base_url}/works/{openalex_id}",
            {
                "select": "referenced_works",
                "api_key": self.api_key,
            },
        )
        identifiers = [value.rsplit("/", 1)[-1] for value in raw.get("referenced_works", [])]
        papers: list[Paper] = []
        for batch in _chunks(identifiers, 50):
            response = self.client.get(
                f"{self.base_url}/works",
                {
                    "filter": f"openalex:{'|'.join(batch)}",
                    "per_page": len(batch),
                    "api_key": self.api_key,
                },
            )
            for item in response.get("results", []):
                reference = self.parse_work(item, self._source_for(item))
                reference.origin = Origin.CITED_REFERENCE
                papers.append(reference)
        return papers

    def _source_for(self, work: dict[str, Any]) -> dict[str, Any] | None:
        source = (work.get("primary_location") or {}).get("source") or {}
        source_id = source.get("id")
        if not source_id:
            return source or None
        short_id = source_id.rsplit("/", 1)[-1]
        if short_id not in self._source_cache:
            self._source_cache[short_id] = self.client.get(
                f"{self.base_url}/sources/{short_id}",
                {"api_key": self.api_key},
            )
        return self._source_cache[short_id]

    @staticmethod
    def parse_work(work: dict[str, Any], source: dict[str, Any] | None = None) -> Paper:
        source = source or (work.get("primary_location") or {}).get("source") or {}
        work_type = _work_type(work.get("type"), source.get("type"))
        record_status = RecordStatus.RETRACTED if work.get("is_retracted") else RecordStatus.ACTIVE
        abstract = _rebuild_abstract(work.get("abstract_inverted_index"))
        ids = {
            key: str(value).removeprefix("https://openalex.org/")
            for key, value in (work.get("ids") or {}).items()
            if value is not None and key != "doi"
        }
        openalex_id = str(work.get("id", "")).rsplit("/", 1)[-1]
        if openalex_id:
            ids["openalex"] = openalex_id
        doi = work.get("doi") or (work.get("ids") or {}).get("doi")
        best_location = work.get("best_oa_location") or work.get("primary_location") or {}
        stats = source.get("summary_stats") or {}
        venue = VenueSignals(
            name=source.get("display_name"),
            venue_type=source.get("type"),
            issn=source.get("issn_l"),
            publisher=source.get("host_organization_name"),
            is_open_access=source.get("is_oa"),
            is_in_doaj=source.get("is_in_doaj"),
            h_index=stats.get("h_index"),
            i10_index=stats.get("i10_index"),
            two_year_mean_citedness=stats.get("2yr_mean_citedness"),
            works_count=source.get("works_count"),
            cited_by_count=source.get("cited_by_count"),
            source="OpenAlex",
        )
        return Paper(
            title=work.get("display_name") or work.get("title") or "Untitled",
            authors=[
                Author(
                    name=(entry.get("author") or {}).get("display_name")
                    or entry.get("raw_author_name"),
                    orcid=(entry.get("author") or {}).get("orcid"),
                )
                for entry in work.get("authorships", [])
                if (entry.get("author") or {}).get("display_name") or entry.get("raw_author_name")
            ],
            abstract=abstract,
            publication_year=work.get("publication_year"),
            publication_date=work.get("publication_date"),
            doi=normalize_doi(doi) if doi else None,
            url=(work.get("primary_location") or {}).get("landing_page_url") or work.get("id"),
            pdf_url=best_location.get("pdf_url"),
            work_type=work_type,
            review_status=_review_status(work_type),
            record_status=record_status,
            venue=venue,
            external_ids=ids,
            topics=[
                topic.get("display_name")
                for topic in work.get("topics", [])
                if topic.get("display_name")
            ],
            cited_by_count=work.get("cited_by_count"),
            open_access_status=(work.get("open_access") or {}).get("oa_status"),
            best_available_version=work.get("best_open_version"),
            discovered_by="OpenAlex",
            metadata={
                "openalex_type": work.get("type"),
                "referenced_works_count": work.get("referenced_works_count"),
                "language": work.get("language"),
            },
        )


def _rebuild_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positioned = ((position, word) for word, positions in index.items() for position in positions)
    return " ".join(word for _, word in sorted(positioned))


def _natural_language_search(query: str) -> str:
    """Remove wildcard syntax when a topic is expressed as ordinary prose."""
    return " ".join(query.translate(str.maketrans({"?": " ", "*": " "})).split())


def _work_type(raw_type: str | None, source_type: str | None) -> WorkType:
    mapping = {
        "preprint": WorkType.PREPRINT,
        "posted-content": WorkType.PREPRINT,
        "report": WorkType.REPORT,
        "dissertation": WorkType.THESIS,
        "book": WorkType.BOOK,
        "book-chapter": WorkType.BOOK_CHAPTER,
        "dataset": WorkType.DATASET,
        "editorial": WorkType.EDITORIAL,
        "erratum": WorkType.CORRECTION,
        "proceedings-article": WorkType.CONFERENCE_PAPER,
    }
    if raw_type in mapping:
        return mapping[raw_type]
    if raw_type == "article" and source_type == "conference":
        return WorkType.CONFERENCE_PAPER
    if raw_type == "article":
        return WorkType.JOURNAL_ARTICLE
    return WorkType.OTHER if raw_type else WorkType.UNKNOWN


def _review_status(work_type: WorkType) -> ReviewStatus:
    if work_type in {WorkType.PREPRINT, WorkType.WORKING_PAPER}:
        return ReviewStatus.NOT_PEER_REVIEWED
    if work_type == WorkType.JOURNAL_ARTICLE:
        return ReviewStatus.LIKELY_PEER_REVIEWED
    if work_type == WorkType.CONFERENCE_PAPER:
        return ReviewStatus.VARIES
    return ReviewStatus.UNKNOWN


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
