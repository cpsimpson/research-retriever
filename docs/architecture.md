# Phase-one architecture

## Data flow

```text
Topic profiles ──> OpenAlex discovery ──> local SQLite catalog
                                              │
Existing Zotero library ──────────────────────┤
                                              │
Crossref versions/references ─────────────────┤
                                              v
                                provenance + suitability signals
                                              │
                           ┌──────────────────┴──────────────────┐
                           v                                     v
                   Zotero managed items                 Obsidian literature notes
                           │                                     │
                           └──────────── daily selector ─────────┘
                                              │
                                              v
                                   dated research round-up
```

The SQLite catalog is coordination state, not a replacement for either application. It stores stable
paper identities, relationships, provenance, read state, note locations, and round-up appearances.

## Stable identity and deduplication

Identity is selected in this order:

1. Normalized DOI
2. OpenAlex, Semantic Scholar, PMID, or arXiv identifier
3. A hash of normalized title, first author, and year

This keeps a paper stable across metadata refreshes while providing a deterministic fallback for older
or unresolved references.

## Provenance

- `manual_zotero`: imported from Zotero without the `rr:managed` tag
- `tool_zotero`: created by Research Retriever
- `discovery`: not yet written to Zotero
- `cited_reference`: imported from a reference list
- `import`: obtained while resolving a related publication version

## Publication suitability

The tool keeps separate fields for:

- work type
- peer-review indication
- active, corrected, retracted, or withdrawn record status
- analysis basis and confidence
- related preprints, versions, and replacements
- venue-level bibliometric and indexing signals

These dimensions must not be collapsed into a single citation-suitability score. Suitability depends on
the claim, field, venue norms, study design, and the researcher's purpose.

Crossref-deposited version links are recorded as verified metadata. When that metadata is absent, the
tool may infer a preprint/publication relationship only when the normalized titles are identical,
author lists overlap, and the publication types are compatible. Both bibliographic records remain in
Zotero and are linked bidirectionally; the weaker preprint is omitted from automatic daily selection.

## Synchronization rules

- Zotero bibliographic metadata wins over previously cached bibliographic metadata.
- Personal prose outside generated markers is never parsed or replaced.
- Unknown Obsidian frontmatter properties are preserved.
- `reading_status` is intentionally shared. When a processed note has a different valid status, the
  Obsidian value is propagated to the catalog and Zotero.
- The first Zotero sync establishes a baseline without bulk analysis.
- Subsequent Zotero items are marked manual or tool-created using `rr:managed`.
- All writes use the Zotero Web API rather than the Zotero SQLite database.

## Reference representation

References are stored as normal Zotero items under one managed collection and linked from the citing
item with `dc:relation`. The local catalog stores a directed `references` edge, and the citing Obsidian
note displays either an Obsidian note link, a Zotero link, a DOI link, or the unresolved deposited
reference key in that order.

This provides navigation without generating a collection or tag for every citing paper.

## Daily selection

Round-ups select only unread or explicitly queued papers that have not appeared previously. The
configured backlog fraction reserves part of the list for manually imported Zotero papers. Any unused
quota spills to the other source, so the round-up can still reach its configured size.

Harvested cited references are excluded from automatic daily selection to avoid flooding the queue;
they can still be explicitly queued or analyzed.

## Analysis boundary

The analysis adapter receives the title, publication/review status, research-interest profile, and
available source text. Structured output requires summary, methods, findings, relevance, limitations,
basis, and confidence. API-side response storage is disabled for the provided OpenAI adapter.

When only an abstract is available, the generated note states `abstract_only`. Missing methods or
findings remain empty rather than being guessed.
