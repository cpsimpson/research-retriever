from datetime import date

from research_retriever.analysis import PaperAnalysis, attach_analysis
from research_retriever.models import Author, Origin, Paper, ReadingStatus, WorkType
from research_retriever.obsidian import GENERATED_END, GENERATED_START, ObsidianWriter


def test_note_updates_generated_content_and_preserves_manual_notes(tmp_path) -> None:
    writer = ObsidianWriter(tmp_path, "Literature", "Roundups")
    paper = Paper(
        title="A useful paper",
        authors=[Author("Ada Lovelace")],
        publication_year=2026,
        work_type=WorkType.JOURNAL_ARTICLE,
        reading_status=ReadingStatus.UNREAD,
    )
    attach_analysis(paper, PaperAnalysis(summary="First summary"))
    path = writer.write_paper_note(paper)
    content = path.read_text()
    content = content.replace("## My notes\n\n", "## My notes\n\nMy durable thought.\n")
    path.write_text(content)

    attach_analysis(paper, PaperAnalysis(summary="Updated summary"))
    writer.write_paper_note(paper)
    updated = path.read_text()
    assert "Updated summary" in updated
    assert "First summary" not in updated
    assert "My durable thought." in updated
    assert updated.count(GENERATED_START) == 1
    assert updated.count(GENERATED_END) == 1


def test_note_preserves_unknown_frontmatter_and_reads_manual_status(tmp_path) -> None:
    writer = ObsidianWriter(tmp_path, "Literature", "Roundups")
    paper = Paper(title="Paper", citation_key="authorPaper2026")
    path = writer.write_paper_note(paper)
    content = path.read_text().replace(
        'reading_status: "unread"', 'reading_status: "read"\nmy_property: "keep me"'
    )
    path.write_text(content)
    assert writer.read_status(paper) == ReadingStatus.READ
    writer.write_paper_note(paper)
    assert 'my_property: "keep me"' in path.read_text()
    assert 'citation_key: "authorPaper2026"' in path.read_text()


def test_roundup_labels_manual_zotero_items(tmp_path) -> None:
    writer = ObsidianWriter(tmp_path, "Literature", "Roundups")
    paper = Paper(title="Backlog paper", origin=Origin.MANUAL_ZOTERO)
    attach_analysis(paper, PaperAnalysis(summary="Worth revisiting."))
    writer.write_paper_note(paper)
    path = writer.write_roundup([paper], date(2026, 7, 22))
    assert "Added manually in Zotero" in path.read_text()
    assert "Worth revisiting" in path.read_text()
