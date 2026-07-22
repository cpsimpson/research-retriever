"""Domain models shared by discovery, Zotero, and Obsidian adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class WorkType(StrEnum):
    JOURNAL_ARTICLE = "journal_article"
    CONFERENCE_PAPER = "conference_paper"
    PREPRINT = "preprint"
    WORKING_PAPER = "working_paper"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    THESIS = "thesis"
    REPORT = "report"
    DATASET = "dataset"
    EDITORIAL = "editorial"
    CORRECTION = "correction"
    OTHER = "other"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    PEER_REVIEWED = "peer_reviewed"
    LIKELY_PEER_REVIEWED = "likely_peer_reviewed"
    NOT_PEER_REVIEWED = "not_peer_reviewed"
    VARIES = "varies"
    UNKNOWN = "unknown"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    CORRECTED = "corrected"
    RETRACTED = "retracted"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class ReadingStatus(StrEnum):
    UNREAD = "unread"
    QUEUED = "queued"
    READING = "reading"
    READ = "read"
    SKIPPED = "skipped"


class Origin(StrEnum):
    DISCOVERY = "discovery"
    MANUAL_ZOTERO = "manual_zotero"
    TOOL_ZOTERO = "tool_zotero"
    CITED_REFERENCE = "cited_reference"
    IMPORT = "import"


class RelationshipType(StrEnum):
    REFERENCES = "references"
    VERSION_OF = "version_of"
    PREPRINT_OF = "preprint_of"
    REPLACES = "replaces"
    RELATED = "related"


@dataclass(slots=True)
class Author:
    name: str
    orcid: str | None = None


@dataclass(slots=True)
class VenueSignals:
    """Transparent venue indicators, not a synthetic quality ranking."""

    name: str | None = None
    venue_type: str | None = None
    issn: str | None = None
    publisher: str | None = None
    is_open_access: bool | None = None
    is_in_doaj: bool | None = None
    h_index: int | None = None
    i10_index: int | None = None
    two_year_mean_citedness: float | None = None
    works_count: int | None = None
    cited_by_count: int | None = None
    source: str | None = None


@dataclass(slots=True)
class Paper:
    title: str
    authors: list[Author] = field(default_factory=list)
    abstract: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    work_type: WorkType = WorkType.UNKNOWN
    review_status: ReviewStatus = ReviewStatus.UNKNOWN
    record_status: RecordStatus = RecordStatus.UNKNOWN
    reading_status: ReadingStatus = ReadingStatus.UNREAD
    origin: Origin = Origin.DISCOVERY
    venue: VenueSignals = field(default_factory=VenueSignals)
    external_ids: dict[str, str] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    cited_by_count: int | None = None
    open_access_status: str | None = None
    best_available_version: str | None = None
    zotero_key: str | None = None
    zotero_version: int | None = None
    obsidian_path: str | None = None
    discovered_by: str | None = None
    added_by_tool: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.doi:
            self.doi = normalize_doi(self.doi)

    @property
    def canonical_key(self) -> str:
        if self.doi:
            return f"doi:{self.doi}"
        for namespace in ("openalex", "semantic_scholar", "pmid", "arxiv"):
            if value := self.external_ids.get(namespace):
                return f"{namespace}:{value.lower()}"
        normalized = re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()
        author = self.authors[0].name.lower() if self.authors else ""
        digest = hashlib.sha256(
            f"{normalized}|{author}|{self.publication_year}".encode()
        ).hexdigest()
        return f"title:{digest[:24]}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> Paper:
        data = json.loads(value)
        data["authors"] = [Author(**author) for author in data.get("authors", [])]
        data["venue"] = VenueSignals(**data.get("venue", {}))
        data["work_type"] = WorkType(data.get("work_type", WorkType.UNKNOWN))
        data["review_status"] = ReviewStatus(data.get("review_status", ReviewStatus.UNKNOWN))
        data["record_status"] = RecordStatus(data.get("record_status", RecordStatus.UNKNOWN))
        data["reading_status"] = ReadingStatus(data.get("reading_status", ReadingStatus.UNREAD))
        data["origin"] = Origin(data.get("origin", Origin.DISCOVERY))
        return cls(**data)


@dataclass(slots=True)
class PaperRelationship:
    source_key: str
    target_key: str
    relationship: RelationshipType
    evidence_source: str
    verified: bool = False


def normalize_doi(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value.rstrip(". ")
