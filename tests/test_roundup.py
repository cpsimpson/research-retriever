from research_retriever.models import Origin, Paper
from research_retriever.store import PaperStore


def test_roundup_blends_new_papers_and_existing_zotero_backlog(tmp_path) -> None:
    store = PaperStore(tmp_path / "catalog.sqlite3")
    store.initialize()
    for index in range(8):
        store.upsert(
            Paper(
                title=f"Backlog {index}",
                doi=f"10.1/backlog-{index}",
                origin=Origin.MANUAL_ZOTERO,
            )
        )
    for index in range(8):
        store.upsert(
            Paper(
                title=f"New {index}",
                doi=f"10.1/new-{index}",
                origin=Origin.TOOL_ZOTERO,
            )
        )

    selected = store.roundup_candidates(5, 0.4)
    assert len(selected) == 5
    assert sum(paper.origin == Origin.MANUAL_ZOTERO for paper in selected) == 2
    assert sum(paper.origin == Origin.TOOL_ZOTERO for paper in selected) == 3

    store.record_roundup("2026-07-22", selected)
    next_selected = store.roundup_candidates(5, 0.4)
    assert {paper.canonical_key for paper in selected}.isdisjoint(
        {paper.canonical_key for paper in next_selected}
    )
