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

