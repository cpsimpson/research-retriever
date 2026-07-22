"""SQLite-backed local catalog."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from research_retriever.models import Paper, PaperRelationship, ReadingStatus, RelationshipType


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    canonical_key TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT NOT NULL,
    publication_year INTEGER,
    work_type TEXT NOT NULL,
    review_status TEXT NOT NULL,
    record_status TEXT NOT NULL,
    reading_status TEXT NOT NULL,
    origin TEXT NOT NULL,
    zotero_key TEXT UNIQUE,
    obsidian_path TEXT,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS papers_doi_unique ON papers(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS papers_reading_status ON papers(reading_status);
CREATE INDEX IF NOT EXISTS papers_origin ON papers(origin);

CREATE TABLE IF NOT EXISTS relationships (
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    relationship TEXT NOT NULL,
    evidence_source TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_key, target_key, relationship),
    FOREIGN KEY (source_key) REFERENCES papers(canonical_key) ON DELETE CASCADE,
    FOREIGN KEY (target_key) REFERENCES papers(canonical_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topic_matches (
    paper_key TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    relevance REAL,
    explanation TEXT,
    PRIMARY KEY (paper_key, topic_id),
    FOREIGN KEY (paper_key) REFERENCES papers(canonical_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS roundup_appearances (
    paper_key TEXT NOT NULL,
    roundup_date TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (paper_key, roundup_date),
    FOREIGN KEY (paper_key) REFERENCES papers(canonical_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class PaperStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def upsert(self, paper: Paper) -> str:
        now = datetime.now(UTC).isoformat()
        key = paper.canonical_key
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO papers (
                    canonical_key, doi, title, publication_year, work_type, review_status,
                    record_status, reading_status, origin, zotero_key, obsidian_path,
                    record_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_key) DO UPDATE SET
                    doi = excluded.doi,
                    title = excluded.title,
                    publication_year = excluded.publication_year,
                    work_type = excluded.work_type,
                    review_status = excluded.review_status,
                    record_status = excluded.record_status,
                    reading_status = excluded.reading_status,
                    origin = excluded.origin,
                    zotero_key = excluded.zotero_key,
                    obsidian_path = excluded.obsidian_path,
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    paper.doi,
                    paper.title,
                    paper.publication_year,
                    paper.work_type,
                    paper.review_status,
                    paper.record_status,
                    paper.reading_status,
                    paper.origin,
                    paper.zotero_key,
                    paper.obsidian_path,
                    paper.to_json(),
                    now,
                    now,
                ),
            )
        return key

    def get(self, key: str) -> Paper | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM papers WHERE canonical_key = ? OR doi = ? OR zotero_key = ?",
                (key, key.removeprefix("doi:"), key),
            ).fetchone()
        return Paper.from_json(row["record_json"]) if row else None

    def add_relationship(self, relationship: PaperRelationship) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO relationships (
                    source_key, target_key, relationship, evidence_source, verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key, target_key, relationship) DO UPDATE SET
                    evidence_source = excluded.evidence_source,
                    verified = excluded.verified
                """,
                (
                    relationship.source_key,
                    relationship.target_key,
                    relationship.relationship,
                    relationship.evidence_source,
                    int(relationship.verified),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def relationships_from(self, key: str) -> list[PaperRelationship]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM relationships WHERE source_key = ? ORDER BY relationship, target_key",
                (key,),
            ).fetchall()
        return [
            PaperRelationship(
                source_key=row["source_key"],
                target_key=row["target_key"],
                relationship=RelationshipType(row["relationship"]),
                evidence_source=row["evidence_source"],
                verified=bool(row["verified"]),
            )
            for row in rows
        ]

    def set_reading_status(self, key: str, status: ReadingStatus) -> Paper:
        paper = self.get(key)
        if paper is None:
            raise KeyError(key)
        paper.reading_status = status
        self.upsert(paper)
        return paper

    def unread(self, limit: int = 100) -> list[Paper]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM papers
                WHERE reading_status IN ('unread', 'queued')
                ORDER BY publication_year DESC NULLS LAST, created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [Paper.from_json(row["record_json"]) for row in rows]

    def set_sync_state(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, datetime.now(UTC).isoformat()),
            )

    def get_sync_state(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
