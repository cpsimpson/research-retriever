"""Crossref metadata and publication-version relationship adapter."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Any

from research_retriever.http import JsonHttpClient
from research_retriever.models import (
    PaperRelationship,
    RelationshipType,
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


def _as_list(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else [value]

