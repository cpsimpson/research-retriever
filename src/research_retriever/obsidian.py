"""Obsidian literature-note and daily-round-up rendering."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from research_retriever.analysis import PaperAnalysis, analysis_for
from research_retriever.models import (
    Origin,
    Paper,
    PaperRelationship,
    ReadingStatus,
    RelationshipType,
)

GENERATED_START = "<!-- research-retriever:generated:start -->"
GENERATED_END = "<!-- research-retriever:generated:end -->"
MANAGED_PROPERTIES = {
    "research_retriever",
    "doi",
    "citation_key",
    "zotero_key",
    "reading_status",
    "publication_type",
    "review_status",
    "record_status",
    "analysis_basis",
    "origin",
}


class ObsidianWriter:
    def __init__(self, vault_path: Path | str, notes_folder: str, roundup_folder: str) -> None:
        self.vault_path = Path(vault_path)
        self.notes_folder = notes_folder
        self.roundup_folder = roundup_folder

    def write_paper_note(
        self,
        paper: Paper,
        relationships: list[PaperRelationship] | None = None,
        related_papers: dict[str, Paper] | None = None,
    ) -> Path:
        path = self._note_path(paper)
        analysis = analysis_for(paper) or PaperAnalysis(
            summary="Analysis pending.", limitations=["No analysis is stored for this paper."]
        )
        properties = _properties(paper, analysis)
        generated = _generated_section(paper, analysis, relationships or [], related_papers or {})
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            body = _replace_generated(existing, generated)
            content = _merge_frontmatter(body, properties)
        else:
            content = _new_note(properties, paper, generated)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paper.obsidian_path = str(path.relative_to(self.vault_path))
        return path

    def read_status(self, paper: Paper) -> ReadingStatus | None:
        path = self._note_path(paper)
        if not path.exists():
            return None
        frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        for line in frontmatter.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "reading_status":
                try:
                    return ReadingStatus(_unquote(value.strip()))
                except ValueError:
                    return None
        return None

    def write_roundup(self, papers: list[Paper], roundup_date: date) -> Path:
        path = self.vault_path / self.roundup_folder / f"{roundup_date.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "---",
            "research_retriever_roundup: true",
            f"date: {roundup_date.isoformat()}",
            "---",
            "",
            f"# Research roundup — {roundup_date.isoformat()}",
            "",
            f"{len(papers)} paper{'s' if len(papers) != 1 else ''} selected for today.",
            "",
        ]
        for index, paper in enumerate(papers, 1):
            analysis = analysis_for(paper)
            note_link = _wiki_link(paper.obsidian_path, paper.title)
            lines.extend(
                [
                    f"## {index}. {note_link}",
                    "",
                    f"- **Source:** {_origin_label(paper.origin)}",
                    f"- **Status:** {paper.work_type.value.replace('_', ' ')}; "
                    f"{paper.review_status.value.replace('_', ' ')}; {paper.record_status.value}",
                    f"- **Reading status:** {paper.reading_status.value}",
                    f"- **Analysis basis:** {analysis.basis if analysis else 'not analyzed'}",
                    "",
                    (
                        analysis.summary
                        if analysis
                        else paper.abstract or "No summary is available."
                    ),
                    "",
                ]
            )
            if analysis and analysis.why_interesting:
                lines.extend([f"**Why it may matter:** {analysis.why_interesting}", ""])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    def _note_path(self, paper: Paper) -> Path:
        if paper.obsidian_path:
            return self.vault_path / paper.obsidian_path
        author = paper.authors[0].name.split()[-1] if paper.authors else "Unknown"
        year = paper.publication_year or "n.d."
        filename = _safe_filename(f"{author} {year} - {paper.title}") + ".md"
        return self.vault_path / self.notes_folder / filename


def _properties(paper: Paper, analysis: PaperAnalysis) -> dict[str, str]:
    return {
        "research_retriever": "true",
        "doi": paper.doi or "",
        "citation_key": paper.citation_key or "",
        "zotero_key": paper.zotero_key or "",
        "reading_status": paper.reading_status.value,
        "publication_type": paper.work_type.value,
        "review_status": paper.review_status.value,
        "record_status": paper.record_status.value,
        "analysis_basis": analysis.basis,
        "origin": paper.origin.value,
    }


def _generated_section(
    paper: Paper,
    analysis: PaperAnalysis,
    relationships: list[PaperRelationship],
    related_papers: dict[str, Paper],
) -> str:
    zotero_link = (
        f"[Open in Zotero](zotero://select/library/items/{paper.zotero_key})"
        if paper.zotero_key
        else "Not yet linked to Zotero"
    )
    h_index = paper.venue.h_index if paper.venue.h_index is not None else "Unknown"
    mean_citedness = (
        paper.venue.two_year_mean_citedness
        if paper.venue.two_year_mean_citedness is not None
        else "Unknown"
    )
    venue_lines = [
        f"- **Venue:** {paper.venue.name or 'Unknown'}",
        f"- **Venue type:** {paper.venue.venue_type or 'Unknown'}",
        f"- **In DOAJ:** {_yes_no_unknown(paper.venue.is_in_doaj)}",
        f"- **Open access:** {_yes_no_unknown(paper.venue.is_open_access)}",
        f"- **Venue h-index:** {h_index}",
        f"- **Two-year mean citedness:** {mean_citedness}",
    ]
    methods = (
        "\n".join(f"- {method}" for method in analysis.methods)
        or "- Not established from the available text."
    )
    findings = (
        "\n".join(f"- {finding}" for finding in analysis.key_findings)
        or "- Not established from the available text."
    )
    limitations = "\n".join(f"- {item}" for item in analysis.limitations) or "- None recorded."
    reference_lines = []
    version_lines = []
    for relation in relationships:
        related = related_papers.get(relation.target_key)
        line = f"- {_paper_link(related)}" if related else f"- `{relation.target_key}`"
        if relation.relationship == RelationshipType.REFERENCES:
            reference_lines.append(line)
        else:
            label = relation.relationship.value.replace("_", " ")
            confidence = "verified metadata" if relation.verified else "inferred match"
            version_lines.append(f"{line} — {label}; {confidence}: {relation.evidence_source}")
    references = "\n".join(reference_lines) or "- References have not been harvested."
    versions = (
        "\n".join(version_lines) or "- No related publication versions are currently recorded."
    )
    return f"""{GENERATED_START}
{zotero_link}

## Suitability for citation

- **Publication type:** {paper.work_type.value.replace("_", " ")}
- **Peer-review indication:** {paper.review_status.value.replace("_", " ")}
- **Record status:** {paper.record_status.value}
- **Best available version:** {paper.best_available_version or "Unknown"}
- **Analysis basis:** {analysis.basis.replace("_", " ")}
- **Analysis confidence:** {analysis.confidence}

## Venue signals

{chr(10).join(venue_lines)}

> Venue indicators are context, not a universal quality score. Citation practices and
> venue norms vary by field.

## Related publication versions

{versions}

## Summary

{analysis.summary}

## Research methods

{methods}

## Key findings

{findings}

## Why this may be interesting

{analysis.why_interesting or "No personalized relevance assessment is available."}

## Analysis limitations

{limitations}

## References cited by this paper

{references}
{GENERATED_END}"""


def _new_note(properties: dict[str, str], paper: Paper, generated: str) -> str:
    frontmatter = _render_frontmatter(properties)
    return f"{frontmatter}\n\n# {paper.title}\n\n{generated}\n\n## My notes\n\n"


def _replace_generated(existing: str, generated: str) -> str:
    pattern = re.compile(rf"{re.escape(GENERATED_START)}.*?{re.escape(GENERATED_END)}", re.DOTALL)
    if pattern.search(existing):
        return pattern.sub(generated, existing, count=1)
    return existing.rstrip() + "\n\n" + generated + "\n"


def _merge_frontmatter(content: str, properties: dict[str, str]) -> str:
    frontmatter, body = _split_frontmatter(content)
    preserved = []
    for line in frontmatter.splitlines():
        key, separator, _ = line.partition(":")
        if not separator or key.strip() not in MANAGED_PROPERTIES:
            preserved.append(line)
    managed = [f"{key}: {_yaml_scalar(value)}" for key, value in properties.items()]
    merged = "\n".join([*preserved, *managed]).strip()
    return f"---\n{merged}\n---\n{body.lstrip()}"


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        return "", content
    boundary = content.find("\n---\n", 4)
    if boundary == -1:
        return "", content
    return content[4:boundary], content[boundary + 5 :]


def _render_frontmatter(properties: dict[str, str]) -> str:
    lines = ["---", *(f"{key}: {_yaml_scalar(value)}" for key, value in properties.items()), "---"]
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    if value in {"true", "false"}:
        return value
    if value == "":
        return '""'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _safe_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|#\^\[\]]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:180] or "Untitled"


def _wiki_link(path: str | None, title: str) -> str:
    if not path:
        return title
    without_extension = path[:-3] if path.endswith(".md") else path
    return f"[[{without_extension}|{title}]]"


def _paper_link(paper: Paper | None) -> str:
    if paper is None:
        return "Unknown related paper"
    if paper.obsidian_path:
        return _wiki_link(paper.obsidian_path, paper.title)
    if paper.zotero_key:
        return f"[{paper.title}](zotero://select/library/items/{paper.zotero_key})"
    if paper.doi:
        return f"[{paper.title}](https://doi.org/{paper.doi})"
    return paper.title


def _yes_no_unknown(value: bool | None) -> str:
    return "Yes" if value is True else "No" if value is False else "Unknown"


def _origin_label(origin: Origin) -> str:
    return {
        Origin.MANUAL_ZOTERO: "Added manually in Zotero",
        Origin.TOOL_ZOTERO: "Found by Research Retriever",
        Origin.DISCOVERY: "Discovered by Research Retriever",
        Origin.CITED_REFERENCE: "Imported from a paper's references",
        Origin.IMPORT: "Imported",
    }[origin]
