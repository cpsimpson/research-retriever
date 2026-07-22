# Research Retriever

Research Retriever is a local-first Python tool that discovers research papers, keeps Zotero and
Obsidian literature notes aligned, and creates a manageable daily reading queue.

The first phase is under active development. Its intended workflow is:

1. Search scholarly indexes using research-topic profiles.
2. Import existing and newly discovered papers into a local catalog.
3. Add selected records and lawful full-text attachments to Zotero.
4. Generate Obsidian notes with protected manual-note sections.
5. Revisit unread Zotero papers gradually in daily round-ups.
6. Harvest cited references and connect them without creating per-paper collection clutter.

## Data ownership

- **Zotero** is authoritative for bibliographic metadata and stored files.
- **Obsidian** is authoritative for personal notes.
- Research Retriever updates only explicitly marked generated sections.
- Secrets are read from environment variables and are never written to the vault or repository.

## Development

The package supports Python 3.11 and newer and intentionally uses the standard library for its
runtime so that the local tool has a small security and maintenance footprint.

```console
python3 -m pytest
PYTHONPATH=src python3 -m research_retriever --help
```

More detailed setup instructions will be added as each integration is completed.
