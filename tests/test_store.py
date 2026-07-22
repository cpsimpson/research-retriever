import sqlite3

import pytest

from research_retriever.models import (
    Paper,
    PaperRelationship,
    ReadingStatus,
    RelationshipType,
)
from research_retriever.store import PaperStore


def test_store_round_trip_and_status_update(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    paper = Paper(title="Stored paper", doi="10.1/stored")
    key = store.upsert(paper)

    assert store.get(key) == paper
    updated = store.set_reading_status(key, ReadingStatus.READ)
    assert updated.reading_status == ReadingStatus.READ
    assert store.unread() == []


def test_relationships_are_idempotent(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    source = Paper(title="Source", doi="10.1/source")
    target = Paper(title="Target", doi="10.1/target")
    store.upsert(source)
    store.upsert(target)
    relationship = PaperRelationship(
        source.canonical_key,
        target.canonical_key,
        RelationshipType.REFERENCES,
        "test fixture",
        True,
    )
    store.add_relationship(relationship)
    store.add_relationship(relationship)
    assert store.relationships_from(source.canonical_key) == [relationship]


def test_store_finds_paper_by_citation_key_and_rejects_ambiguity(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    first = Paper(title="First", citation_key="authorUsefulPaper", zotero_key="FIRST123")
    store.upsert(first)

    assert store.get("authorUsefulPaper") == first
    assert store.get("AUTHORUSEFULPAPER") == first

    store.upsert(Paper(title="Second", citation_key="authorUsefulPaper", zotero_key="SECOND12"))
    with pytest.raises(ValueError, match="Citation key is ambiguous"):
        store.get("authorUsefulPaper")


def test_store_migrates_catalogs_created_before_citation_keys(tmp_path) -> None:
    path = tmp_path / "catalog.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE papers (
                canonical_key TEXT PRIMARY KEY, doi TEXT, title TEXT NOT NULL,
                publication_year INTEGER, work_type TEXT NOT NULL,
                review_status TEXT NOT NULL, record_status TEXT NOT NULL,
                reading_status TEXT NOT NULL, origin TEXT NOT NULL,
                zotero_key TEXT UNIQUE, obsidian_path TEXT, record_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )

    store = PaperStore(path)
    store.initialize()

    with store.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(papers)")}
    assert "citation_key" in columns
