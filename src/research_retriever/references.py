"""Extract structured citations from a manuscript's reference section."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from research_retriever.http import JsonHttpClient
from research_retriever.models import normalize_doi


@dataclass(slots=True, frozen=True)
class ExtractedReference:
    raw: str
    title: str = ""
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None


class ReferenceParser(Protocol):
    def parse(self, document_text: str) -> list[ExtractedReference]: ...


class HeuristicReferenceParser:
    """Conservative fallback that extracts only references containing a DOI."""

    def parse(self, document_text: str) -> list[ExtractedReference]:
        section = reference_section(document_text)
        output: list[ExtractedReference] = []
        seen: set[str] = set()
        for match in DOI_PATTERN.finditer(section):
            doi = normalize_doi(match.group(0))
            if doi in seen:
                continue
            seen.add(doi)
            start = max(section.rfind("\n", 0, match.start()), 0)
            end = section.find("\n", match.end())
            raw = section[start : end if end >= 0 else len(section)].strip()
            output.append(ExtractedReference(raw=raw, doi=doi))
        return output


class OllamaReferenceParser:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        client: JsonHttpClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client or JsonHttpClient(
            user_agent="research-retriever/0.1",
            timeout=300,
        )

    def parse(self, document_text: str) -> list[ExtractedReference]:
        section = reference_section(document_text)
        extracted: list[ExtractedReference] = []
        for chunk in _chunks(section):
            response = self.client.request_json(
                "POST",
                f"{self.base_url}/api/chat",
                {
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": REFERENCE_SCHEMA,
                    "options": {"temperature": 0},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Extract bibliography entries exactly and conservatively. "
                                "Do not invent missing titles, authors, years, or DOIs. Return "
                                "only JSON matching the supplied schema."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Extract every complete reference in this text:\n\n{chunk}",
                        },
                    ],
                },
            )
            content = (response.get("message") or {}).get("content")
            if not content:
                raise RuntimeError("Ollama returned no reference extraction content")
            for item in json.loads(content).get("references", []):
                year = str(item.get("year") or "")
                raw_doi = item.get("doi") or _doi(item.get("raw") or "")
                extracted.append(
                    ExtractedReference(
                        raw=str(item.get("raw") or "").strip(),
                        title=str(item.get("title") or "").strip(),
                        authors=tuple(
                            str(author).strip()
                            for author in item.get("authors", [])
                            if str(author).strip()
                        ),
                        year=int(year) if year.isdigit() else None,
                        doi=normalize_doi(str(raw_doi)) if raw_doi else None,
                    )
                )
        unique: dict[str, ExtractedReference] = {}
        for item in extracted:
            key = item.doi or _normalize(item.title) or _normalize(item.raw)
            if key:
                unique.setdefault(key, item)
        return list(unique.values())


def reference_section(document_text: str) -> str:
    matches = list(
        re.finditer(
            r"(?im)^\s*(?:references(?:\s+(?:and|&)\s+recommended\s+reading)?|"
            r"bibliography|works cited)\s*:?\s*$",
            document_text,
        )
    )
    if not matches:
        raise RuntimeError(
            "No References, Bibliography, or Works Cited heading was found in the PDF"
        )
    section = document_text[matches[-1].end() :].strip()
    if len(section) < 10:
        raise RuntimeError("The reference section in the PDF did not contain extractable text")
    return section


def _chunks(text: str, maximum: int = 14_000) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= maximum:
            chunks.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, maximum)
        boundary = boundary if boundary > maximum // 2 else maximum
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return chunks


def _doi(value: str) -> str | None:
    match = DOI_PATTERN.search(value)
    return match.group(0) if match else None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)

REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                    "year": {"type": "string"},
                    "doi": {"type": "string"},
                },
                "required": ["raw", "title", "authors", "year", "doi"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["references"],
    "additionalProperties": False,
}
