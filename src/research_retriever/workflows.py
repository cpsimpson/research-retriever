"""Application workflows that coordinate providers and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from research_retriever.analysis import Analyzer, PendingAnalyzer, analysis_for, attach_analysis
from research_retriever.models import (
    Origin,
    Paper,
    PaperRelationship,
    RelationshipType,
)
from research_retriever.obsidian import ObsidianWriter
from research_retriever.providers.crossref import CrossrefProvider
from research_retriever.providers.openalex import OpenAlexProvider
from research_retriever.settings import TopicSettings
from research_retriever.store import PaperStore
from research_retriever.zotero import ZoteroClient, paper_from_zotero


@dataclass(slots=True)
class SyncResult:
    imported: int = 0
    manual: int = 0
    tool_managed: int = 0
    latest_zotero_version: int = 0
    initial_import: bool = False
    papers: list[Paper] | None = None


@dataclass(slots=True)
class HarvestResult:
    retrieved: int
    created: int
    already_present: int
    papers: list[Paper]


class ResearchWorkflow:
    def __init__(
        self,
        store: PaperStore,
        zotero: ZoteroClient,
        openalex: OpenAlexProvider | None = None,
        crossref: CrossrefProvider | None = None,
        analyzer: Analyzer | None = None,
        obsidian: ObsidianWriter | None = None,
    ) -> None:
        self.store = store
        self.zotero = zotero
        self.openalex = openalex
        self.crossref = crossref
        self.analyzer = analyzer or PendingAnalyzer()
        self.obsidian = obsidian

    def sync_zotero(self, incremental: bool = True) -> SyncResult:
        since = self.store.get_sync_state("zotero_library_version") if incremental else None
        items = self.zotero.list_top_items(int(since) if since else None)
        result = SyncResult(initial_import=since is None, papers=[])
        for item in items:
            paper = paper_from_zotero(item)
            existing = self.store.get(paper.canonical_key)
            if existing:
                paper.obsidian_path = existing.obsidian_path
                paper.metadata = {**existing.metadata, **paper.metadata}
            self.store.upsert(paper)
            result.papers.append(paper)
            result.imported += 1
            result.tool_managed += int(paper.added_by_tool)
            result.manual += int(not paper.added_by_tool)
            result.latest_zotero_version = max(
                result.latest_zotero_version, paper.zotero_version or 0
            )
        if result.latest_zotero_version:
            self.store.set_sync_state("zotero_library_version", str(result.latest_zotero_version))
        return result

    def discover_topic(self, topic: TopicSettings, limit: int = 25) -> list[Paper]:
        if self.openalex is None:
            raise RuntimeError("OpenAlex must be configured to discover papers")
        candidates = [
            paper
            for paper in self.openalex.discover(topic.query, limit)
            if _matches_terms(paper, topic.include_terms, topic.exclude_terms)
        ]
        inbox = self.zotero.ensure_collection_path(self.zotero.settings.inbox_collection)
        output: list[Paper] = []
        for paper in candidates:
            existing = self.store.get(paper.canonical_key)
            if existing:
                output.append(existing)
                continue
            paper.metadata["matched_topic_id"] = topic.id
            paper.metadata["matched_interest"] = topic.interest
            paper = self.zotero.create_papers([paper], inbox)[0]
            self.check_updated_versions(paper, inbox)
            self.analyze_and_write(paper, topic.interest)
            self.store.record_topic_match(
                paper.canonical_key,
                topic.id,
                None,
                f"Matched the OpenAlex search for {topic.name}",
            )
            output.append(paper)
        return output

    def analyze_and_write(
        self, paper: Paper, research_interest: str = "", force: bool = False
    ) -> Paper:
        if self.openalex and paper.doi and not paper.external_ids.get("openalex"):
            try:
                paper = _merge_papers(paper, self.openalex.get_work_by_doi(paper.doi))
            except Exception as exc:  # Keep sync useful when an enrichment provider is unavailable.
                paper.metadata["openalex_enrichment_error"] = str(exc)
        if force or analysis_for(paper) is None:
            analysis = self.analyzer.analyze(paper, research_interest or _paper_interest(paper))
            attach_analysis(paper, analysis)
        self.store.upsert(paper)
        return self.write_note(paper, reconcile_status=True)

    def write_note(self, paper: Paper, reconcile_status: bool = True) -> Paper:
        if self.obsidian:
            note_status = self.obsidian.read_status(paper)
            if reconcile_status and note_status is not None and note_status != paper.reading_status:
                paper.reading_status = note_status
                self.store.upsert(paper)
                if paper.zotero_key:
                    self.zotero.set_reading_status(paper.zotero_key, note_status)
            self.obsidian.write_paper_note(
                paper,
                self.store.relationships_from(paper.canonical_key),
                self.store.related_papers(paper.canonical_key),
            )
            self.store.upsert(paper)
        return paper

    def process_new_zotero_items(
        self, result: SyncResult, research_interest: str = ""
    ) -> list[Paper]:
        if result.initial_import:
            return []
        return [
            self.analyze_and_write(paper, research_interest, force=True)
            for paper in result.papers or []
        ]

    def create_daily_roundup(
        self,
        roundup_date: date,
        limit: int,
        backlog_fraction: float,
        research_interest: str,
    ) -> tuple[list[Paper], object | None]:
        papers = self.store.roundup_candidates(limit, backlog_fraction)
        processed = [self.analyze_and_write(paper, research_interest) for paper in papers]
        self.store.record_roundup(roundup_date.isoformat(), processed)
        path = self.obsidian.write_roundup(processed, roundup_date) if self.obsidian else None
        return processed, path

    def check_updated_versions(
        self, paper: Paper, collection_key: str | None = None
    ) -> list[Paper]:
        if self.crossref is None or self.openalex is None or not paper.doi:
            return []
        versions: list[Paper] = []
        try:
            relationships = self.crossref.version_relationships(paper.doi)
        except Exception as exc:
            paper.metadata["version_check_error"] = str(exc)
            self.store.upsert(paper)
            return []
        for relationship in relationships:
            related_key = (
                relationship.target_key
                if relationship.source_key == paper.canonical_key
                else relationship.source_key
            )
            related = self.store.get(related_key)
            if related is None:
                try:
                    related = self.openalex.get_work_by_doi(related_key.removeprefix("doi:"))
                except Exception:
                    continue
                related.origin = Origin.IMPORT
                related.metadata["found_as_updated_version_of"] = paper.canonical_key
                if not related.zotero_key:
                    related = self.zotero.create_papers([related], collection_key)[0]
                self.store.upsert(related)
            self.store.add_relationship(relationship)
            versions.append(related)
        if versions:
            paper.metadata["updated_versions"] = [version.canonical_key for version in versions]
            self.store.upsert(paper)
        return versions

    def harvest_references(self, paper: Paper) -> HarvestResult:
        candidates: list[Paper] = []
        if self.openalex and paper.external_ids.get("openalex"):
            candidates.extend(self.openalex.references(paper))
        if self.crossref and paper.doi:
            candidates.extend(self.crossref.references(paper.doi))
        if not candidates:
            raise RuntimeError(
                "No reference list was available from OpenAlex or Crossref for this paper"
            )
        unique: dict[str, Paper] = {}
        for reference in candidates:
            unique.setdefault(reference.canonical_key, reference)
        references = list(unique.values())
        collection = self.zotero.ensure_collection_path(self.zotero.settings.references_collection)
        existing_by_key: dict[str, Paper] = {}
        unknown: list[Paper] = []
        for reference in references:
            existing = self.store.get(reference.canonical_key)
            if existing and existing.zotero_key:
                existing_by_key[reference.canonical_key] = existing
            else:
                if self.openalex and reference.doi and not reference.external_ids.get("openalex"):
                    try:
                        reference = self.openalex.get_work_by_doi(reference.doi)
                        reference.origin = Origin.CITED_REFERENCE
                    except Exception:
                        pass
                unknown.append(reference)
        created = self.zotero.create_papers(unknown, collection) if unknown else []
        for reference in created:
            self.store.upsert(reference)

        linked: list[Paper] = []
        for reference in references:
            reference = existing_by_key.get(reference.canonical_key) or self.store.get(
                reference.canonical_key
            )
            if reference is None:
                continue
            linked.append(reference)
            self.store.add_relationship(
                PaperRelationship(
                    source_key=paper.canonical_key,
                    target_key=reference.canonical_key,
                    relationship=RelationshipType.REFERENCES,
                    evidence_source=reference.discovered_by or "scholarly reference metadata",
                    verified=bool(reference.doi or reference.external_ids.get("openalex")),
                )
            )
        if paper.zotero_key:
            self.zotero.link_references(
                paper.zotero_key,
                (reference.zotero_key for reference in linked if reference.zotero_key),
            )
        if self.obsidian:
            self.obsidian.write_paper_note(
                paper,
                self.store.relationships_from(paper.canonical_key),
                self.store.related_papers(paper.canonical_key),
            )
        return HarvestResult(
            retrieved=len(references),
            created=len(created),
            already_present=len(existing_by_key),
            papers=linked,
        )


def _matches_terms(paper: Paper, include: tuple[str, ...], exclude: tuple[str, ...]) -> bool:
    haystack = f"{paper.title}\n{paper.abstract or ''}".lower()
    if include and not any(term.lower() in haystack for term in include):
        return False
    return not any(term.lower() in haystack for term in exclude)


def _merge_papers(local: Paper, enriched: Paper) -> Paper:
    enriched.reading_status = local.reading_status
    enriched.origin = local.origin
    enriched.zotero_key = local.zotero_key
    enriched.zotero_version = local.zotero_version
    enriched.obsidian_path = local.obsidian_path
    enriched.added_by_tool = local.added_by_tool
    enriched.metadata = {**enriched.metadata, **local.metadata}
    return enriched


def _paper_interest(paper: Paper) -> str:
    return str(paper.metadata.get("matched_interest", ""))
