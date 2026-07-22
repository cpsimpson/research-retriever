"""Zotero Web API adapter with conservative, version-aware writes."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from research_retriever.http import JsonHttpClient
from research_retriever.models import (
    Author,
    Origin,
    Paper,
    ReadingStatus,
    RecordStatus,
    ReviewStatus,
    VenueSignals,
    WorkType,
    normalize_doi,
)
from research_retriever.settings import ZoteroSettings

READING_TAGS = {
    ReadingStatus.QUEUED: "rr:queued",
    ReadingStatus.READING: "rr:reading",
    ReadingStatus.READ: "rr:read",
    ReadingStatus.SKIPPED: "rr:skipped",
}
ALL_READING_TAGS = frozenset(READING_TAGS.values())

ZOTERO_TYPES = {
    WorkType.JOURNAL_ARTICLE: "journalArticle",
    WorkType.CONFERENCE_PAPER: "conferencePaper",
    WorkType.PREPRINT: "preprint",
    WorkType.WORKING_PAPER: "report",
    WorkType.BOOK: "book",
    WorkType.BOOK_CHAPTER: "bookSection",
    WorkType.THESIS: "thesis",
    WorkType.REPORT: "report",
    WorkType.DATASET: "dataset",
    WorkType.EDITORIAL: "journalArticle",
    WorkType.CORRECTION: "journalArticle",
    WorkType.OTHER: "document",
    WorkType.UNKNOWN: "document",
}


class ZoteroClient:
    base_url = "https://api.zotero.org"

    def __init__(self, settings: ZoteroSettings, client: JsonHttpClient | None = None) -> None:
        if settings.library_type not in {"user", "group"}:
            raise ValueError("Zotero library_type must be 'user' or 'group'")
        if not settings.api_key:
            raise ValueError(f"Set the Zotero key in {settings.api_key_env}")
        self.settings = settings
        self.client = client or JsonHttpClient(
            user_agent="research-retriever/0.1",
            default_headers={
                "Zotero-API-Key": settings.api_key,
                "Zotero-API-Version": "3",
            },
        )
        prefix = "users" if settings.library_type == "user" else "groups"
        self.library_path = f"/{prefix}/{settings.library_id}"
        self._templates: dict[str, dict[str, Any]] = {}

    def validate_key(self) -> dict[str, Any]:
        return self.client.get(f"{self.base_url}/keys/current")

    def list_top_items(self, since: int | None = None) -> list[dict[str, Any]]:
        return self._paginate(
            f"{self.library_path}/items/top",
            {"format": "json", "since": since},
        )

    def get_item(self, key: str) -> dict[str, Any]:
        return self.client.get(f"{self.base_url}{self.library_path}/items/{key}")

    def create_papers(
        self, papers: Iterable[Paper], collection_key: str | None = None
    ) -> list[Paper]:
        output: list[Paper] = []
        for batch in _chunks(list(papers), 50):
            payload = [self.paper_payload(paper, collection_key) for paper in batch]
            response = self.client.request_json(
                "POST", f"{self.base_url}{self.library_path}/items", payload
            )
            failed = response.get("failed", {})
            if failed:
                raise RuntimeError(f"Zotero rejected {len(failed)} item(s): {failed}")
            for index, paper in enumerate(batch):
                key = _write_key(response, index)
                if not key:
                    raise RuntimeError(f"Zotero did not return a key for item {index}")
                paper.zotero_key = key
                paper.added_by_tool = True
                paper.origin = (
                    Origin.CITED_REFERENCE
                    if paper.origin == Origin.CITED_REFERENCE
                    else Origin.TOOL_ZOTERO
                )
                output.append(paper)
        return output

    def paper_payload(self, paper: Paper, collection_key: str | None = None) -> dict[str, Any]:
        item_type = ZOTERO_TYPES[paper.work_type]
        template = copy.deepcopy(self.item_template(item_type))
        candidates: dict[str, Any] = {
            "title": paper.title,
            "abstractNote": paper.abstract or "",
            "date": paper.publication_date or str(paper.publication_year or ""),
            "DOI": paper.doi or "",
            "url": paper.url or "",
            "publicationTitle": paper.venue.name or "",
            "proceedingsTitle": paper.venue.name or "",
            "conferenceName": paper.venue.name or "",
            "repository": paper.venue.name or "",
            "institution": paper.venue.publisher or "",
        }
        for key, value in candidates.items():
            if key in template:
                template[key] = value
        template["creators"] = [_author_payload(author) for author in paper.authors]
        tags = [{"tag": "rr:managed"}]
        if paper.origin == Origin.CITED_REFERENCE:
            tags.append({"tag": "rr:reference"})
        if status_tag := READING_TAGS.get(paper.reading_status):
            tags.append({"tag": status_tag})
        tags.extend({"tag": f"rr:type:{paper.work_type.value}"} for _ in [0])
        template["tags"] = tags
        template["collections"] = [collection_key] if collection_key else []
        template["relations"] = template.get("relations", {})
        return template

    def item_template(self, item_type: str) -> dict[str, Any]:
        if item_type not in self._templates:
            self._templates[item_type] = self.client.get(
                f"{self.base_url}/items/new", {"itemType": item_type}
            )
        return self._templates[item_type]

    def ensure_collection_path(self, path: str) -> str:
        parent: str | None = None
        traversed: list[str] = []
        for name in (part.strip() for part in path.split("/") if part.strip()):
            traversed.append(name)
            match = next(
                (
                    item
                    for item in self.list_collections()
                    if item["data"]["name"] == name
                    and (item["data"].get("parentCollection") or None) == parent
                ),
                None,
            )
            if match:
                parent = match["key"]
                continue
            payload = [{"name": name, "parentCollection": parent or False}]
            response = self.client.request_json(
                "POST", f"{self.base_url}{self.library_path}/collections", payload
            )
            failed = response.get("failed", {})
            if failed:
                raise RuntimeError(f"Unable to create collection {'/'.join(traversed)}: {failed}")
            parent = _write_key(response, 0)
            if not parent:
                raise RuntimeError(
                    f"Zotero did not return a collection key for {'/'.join(traversed)}"
                )
        if parent is None:
            raise ValueError("Collection path cannot be empty")
        return parent

    def list_collections(self) -> list[dict[str, Any]]:
        return self._paginate(f"{self.library_path}/collections", {})

    def set_reading_status(self, item_key: str, status: ReadingStatus) -> None:
        item = self.get_item(item_key)
        data = item["data"]
        tags = [tag for tag in data.get("tags", []) if tag.get("tag") not in ALL_READING_TAGS]
        if new_tag := READING_TAGS.get(status):
            tags.append({"tag": new_tag})
        self.client.request_json(
            "PATCH",
            f"{self.base_url}{self.library_path}/items/{item_key}",
            {"tags": tags},
            {"If-Unmodified-Since-Version": str(data["version"])},
        )

    def link_references(self, parent_key: str, reference_keys: Iterable[str]) -> None:
        item = self.get_item(parent_key)
        data = item["data"]
        relations = copy.deepcopy(data.get("relations") or {})
        existing = relations.get("dc:relation", [])
        if isinstance(existing, str):
            existing = [existing]
        values = set(existing)
        values.update(self.item_uri(key) for key in reference_keys)
        relations["dc:relation"] = sorted(values)
        self.client.request_json(
            "PATCH",
            f"{self.base_url}{self.library_path}/items/{parent_key}",
            {"relations": relations},
            {"If-Unmodified-Since-Version": str(data["version"])},
        )

    def item_uri(self, key: str) -> str:
        prefix = "users" if self.settings.library_type == "user" else "groups"
        return f"http://zotero.org/{prefix}/{self.settings.library_id}/items/{key}"

    def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self.client.get(
                f"{self.base_url}{path}", {**params, "limit": 100, "start": start}
            )
            output.extend(page)
            if len(page) < 100:
                return output
            start += len(page)


def paper_from_zotero(item: dict[str, Any]) -> Paper:
    data = item.get("data", item)
    tags = {tag.get("tag") for tag in data.get("tags", [])}
    managed = "rr:managed" in tags
    reading_status = next(
        (status for status, tag in READING_TAGS.items() if tag in tags), ReadingStatus.UNREAD
    )
    work_type = _from_zotero_type(data.get("itemType"), tags)
    doi = data.get("DOI") or _doi_from_extra(data.get("extra", ""))
    citation_key = data.get("citationKey") or _citation_key_from_extra(data.get("extra", ""))
    return Paper(
        title=data.get("title") or "Untitled",
        authors=[
            Author(
                name=creator.get("name")
                or " ".join(
                    value for value in (creator.get("firstName"), creator.get("lastName")) if value
                )
            )
            for creator in data.get("creators", [])
            if creator.get("name") or creator.get("firstName") or creator.get("lastName")
        ],
        abstract=data.get("abstractNote") or None,
        publication_year=_year(data.get("date")),
        publication_date=data.get("date") or None,
        doi=normalize_doi(doi) if doi else None,
        url=data.get("url") or None,
        work_type=work_type,
        review_status=_review_status(work_type),
        record_status=(
            RecordStatus.RETRACTED
            if "retracted" in {str(tag).lower() for tag in tags}
            else RecordStatus.ACTIVE
        ),
        reading_status=reading_status,
        origin=Origin.TOOL_ZOTERO if managed else Origin.MANUAL_ZOTERO,
        venue=VenueSignals(
            name=data.get("publicationTitle")
            or data.get("proceedingsTitle")
            or data.get("repository")
            or None,
            issn=data.get("ISSN") or None,
            publisher=data.get("publisher") or data.get("institution") or None,
            source="Zotero",
        ),
        citation_key=citation_key or None,
        zotero_key=data.get("key") or item.get("key"),
        zotero_version=data.get("version") or item.get("version"),
        added_by_tool=managed,
        metadata={"zotero_item_type": data.get("itemType")},
    )


def _author_payload(author: Author) -> dict[str, str]:
    parts = author.name.rsplit(" ", 1)
    if len(parts) == 1:
        return {"creatorType": "author", "name": author.name}
    return {"creatorType": "author", "firstName": parts[0], "lastName": parts[1]}


def _from_zotero_type(item_type: str | None, tags: set[str | None]) -> WorkType:
    tagged = next(
        (tag.removeprefix("rr:type:") for tag in tags if tag and tag.startswith("rr:type:")), None
    )
    if tagged:
        try:
            return WorkType(tagged)
        except ValueError:
            pass
    mapping = {
        "journalArticle": WorkType.JOURNAL_ARTICLE,
        "conferencePaper": WorkType.CONFERENCE_PAPER,
        "preprint": WorkType.PREPRINT,
        "book": WorkType.BOOK,
        "bookSection": WorkType.BOOK_CHAPTER,
        "thesis": WorkType.THESIS,
        "report": WorkType.REPORT,
        "dataset": WorkType.DATASET,
    }
    return mapping.get(item_type, WorkType.UNKNOWN)


def _review_status(work_type: WorkType) -> ReviewStatus:
    if work_type in {WorkType.PREPRINT, WorkType.WORKING_PAPER}:
        return ReviewStatus.NOT_PEER_REVIEWED
    if work_type == WorkType.JOURNAL_ARTICLE:
        return ReviewStatus.LIKELY_PEER_REVIEWED
    if work_type == WorkType.CONFERENCE_PAPER:
        return ReviewStatus.VARIES
    return ReviewStatus.UNKNOWN


def _doi_from_extra(extra: str) -> str | None:
    for line in extra.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "doi":
            return value.strip()
    return None


def _citation_key_from_extra(extra: str) -> str | None:
    for line in extra.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower().replace(" ", "") == "citationkey":
            return value.strip()
    return None


def _year(value: str | None) -> int | None:
    if not value:
        return None
    for token in value.replace("/", "-").split("-"):
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None


def _chunks(values: list[Paper], size: int) -> Iterable[list[Paper]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _write_key(response: dict[str, Any], index: int) -> str | None:
    value = response.get("successful", response.get("success", {})).get(str(index))
    return value.get("key") if isinstance(value, dict) else value
