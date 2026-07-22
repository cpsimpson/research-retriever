"""Application workflows that coordinate providers and adapters."""

from __future__ import annotations

from dataclasses import dataclass

from research_retriever.models import Paper, PaperRelationship, RelationshipType
from research_retriever.providers.openalex import OpenAlexProvider
from research_retriever.store import PaperStore
from research_retriever.zotero import ZoteroClient, paper_from_zotero


@dataclass(slots=True)
class SyncResult:
    imported: int = 0
    manual: int = 0
    tool_managed: int = 0
    latest_zotero_version: int = 0


class ResearchWorkflow:
    def __init__(
        self,
        store: PaperStore,
        zotero: ZoteroClient,
        openalex: OpenAlexProvider | None = None,
    ) -> None:
        self.store = store
        self.zotero = zotero
        self.openalex = openalex

    def sync_zotero(self, incremental: bool = True) -> SyncResult:
        since = self.store.get_sync_state("zotero_library_version") if incremental else None
        items = self.zotero.list_top_items(int(since) if since else None)
        result = SyncResult()
        for item in items:
            paper = paper_from_zotero(item)
            self.store.upsert(paper)
            result.imported += 1
            result.tool_managed += int(paper.added_by_tool)
            result.manual += int(not paper.added_by_tool)
            result.latest_zotero_version = max(
                result.latest_zotero_version, paper.zotero_version or 0
            )
        if result.latest_zotero_version:
            self.store.set_sync_state(
                "zotero_library_version", str(result.latest_zotero_version)
            )
        return result

    def harvest_references(self, paper: Paper) -> list[Paper]:
        if self.openalex is None:
            raise RuntimeError("OpenAlex must be configured to harvest references")
        references = self.openalex.references(paper)
        collection = self.zotero.ensure_collection_path(
            self.zotero.settings.references_collection
        )
        created: list[Paper] = []
        linked: list[Paper] = []
        for reference in references:
            existing = self.store.get(reference.canonical_key)
            if existing and existing.zotero_key:
                reference = existing
            else:
                reference = self.zotero.create_papers([reference], collection)[0]
                self.store.upsert(reference)
                created.append(reference)
            linked.append(reference)
            self.store.add_relationship(
                PaperRelationship(
                    source_key=paper.canonical_key,
                    target_key=reference.canonical_key,
                    relationship=RelationshipType.REFERENCES,
                    evidence_source="OpenAlex referenced_works",
                    verified=True,
                )
            )
        if paper.zotero_key:
            self.zotero.link_references(
                paper.zotero_key,
                (reference.zotero_key for reference in linked if reference.zotero_key),
            )
        return created
