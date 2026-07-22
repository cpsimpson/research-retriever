# Research Retriever

Research Retriever is a local-first Python tool that discovers research papers, keeps bibliographic
records in Zotero, writes protected literature notes in Obsidian, and creates a manageable daily
reading queue.

This repository contains the phase-one command-line application. It is intentionally conservative:
it distinguishes full-text and abstract-only analysis, preserves personal notes, records provenance,
and exposes venue indicators instead of pretending that one universal journal-quality score exists.

## Phase-one features

- Search configured research topics through OpenAlex.
- Import existing Zotero papers into a local SQLite catalog.
- Detect whether a Zotero item was added manually or by Research Retriever.
- Add discoveries to a managed Zotero inbox without duplicating known DOIs.
- Label journal articles, conference papers, preprints, working papers, reports, theses, datasets,
  books, chapters, editorials, corrections, retractions, and unknown records.
- Record explicit Crossref version relationships and conservatively infer preprint/publication pairs
  when normalized titles are identical and author lists overlap.
- Display transparent venue signals from OpenAlex, including venue type, DOAJ status, open-access
  status, h-index, i10-index, and two-year mean citedness when available.
- Harvest cited references from OpenAlex and Crossref, create missing Zotero records in batches, and
  connect them to the citing paper using Zotero related-item links.
- Track `unread`, `queued`, `reading`, `read`, and `skipped` states.
- Generate grounded summaries, methods, findings, limitations, and personalized relevance using an
  optional structured-output analyzer.
- Preserve all manual Obsidian prose outside explicit generated markers.
- Blend new discoveries with unread papers from the existing Zotero backlog in bounded daily
  round-ups.

## Design decisions

- **Zotero owns bibliography and files.** Research Retriever never edits Zotero's database directly.
- **Obsidian owns personal prose.** Only frontmatter fields listed as managed and content between
  `research-retriever:generated` markers are replaced.
- **The first Zotero sync is a baseline.** It catalogs the existing library without analyzing every
  item or generating thousands of notes. Backlog papers are processed gradually in daily round-ups.
- **Missing read tags mean unread.** The tool does not add an `unread` tag to every existing item.
- **References use one collection.** They live under `Research Retriever/References`, carry a small
  provenance tag, and are linked as Zotero related items. No per-paper collection explosion is
  created.
- **AI absence is explicit.** Without an analysis key, notes say `Analysis pending`; the program does
  not manufacture methods or findings from metadata.

See [the architecture notes](docs/architecture.md) for the data flow and conflict rules.

## Requirements

- Python 3.11 or newer
- A Zotero account and a dedicated Web API key with read/write access to the target library
- A free OpenAlex API key for discovery and citation-graph access
- An Obsidian vault on the machine running the tool
- Optional: a local Ollama installation or an OpenAI API key for structured paper analysis

Ollama is the recommended no-per-request-fee option and keeps source text on the local machine. OpenAI API
access and a ChatGPT subscription are separate products; OpenAI remains available as an optional
separately billed provider.

## Install for development

```console
git clone <this-repository>
cd research-retriever
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
```

The application has no third-party runtime dependencies. Development dependencies are isolated in
the `dev` extra.

## Configure

Create dedicated API keys rather than putting service passwords in configuration files.

```console
export ZOTERO_API_KEY="replace-with-a-dedicated-zotero-key"
export OPENALEX_API_KEY="replace-with-an-openalex-key"
export OPENAI_API_KEY="replace-with-an-openai-api-key"  # optional
```

Never commit these values. For routine use, store them in the operating system's credential manager
and expose them to the scheduled process at runtime.

For local analysis, start Ollama and select an installed model:

```toml
[providers]
analysis_provider = "ollama"
analysis_model = "gemma4:31b"
analysis_base_url = "http://127.0.0.1:11434"
```

No analysis API key is required. `research-retriever doctor` verifies both the Ollama service and
the configured model. The native Ollama integration sends a JSON schema, disables streaming and
model thinking output, and uses temperature zero for repeatable structured notes.

To use the separately billed OpenAI API instead:

```toml
[providers]
analysis_provider = "openai"
analysis_model = "gpt-5.6-luna"
analysis_api_key_env = "OPENAI_API_KEY"
```

Create a starter configuration:

```console
research-retriever init \
  --vault "/absolute/path/to/Obsidian Vault" \
  --zotero-library-id "1234567" \
  --email "researcher@example.edu"
```

On macOS the default configuration is:

```text
~/Library/Application Support/research-retriever/config.toml
```

The contact email identifies this client to Crossref; it is not used to sign in or send email.
OpenAlex now relies on its API key instead. The numeric Zotero user ID is shown on Zotero's API-key
page. For a group library, change
`library_type` to `group` and use the numeric group ID. Edit the generated `[[topics]]` entries to
describe real research interests. Multiple topic blocks are supported.

An annotated example is available at [config.example.toml](config.example.toml).

## First run

Check access without modifying the library:

```console
research-retriever doctor
```

Catalog the existing Zotero library:

```console
research-retriever sync
```

The first sync is deliberately quiet: it records the backlog but does not analyze it. Later syncs
process newly added or changed Zotero items and mark untagged items as `manual_zotero` provenance.

## Everyday commands

Find papers for every configured topic:

```console
research-retriever discover --limit 10
```

Run one topic:

```console
research-retriever discover --topic example-topic --limit 10
```

Create today's bounded reading list:

```console
research-retriever daily
```

Harvest the references of a cataloged paper:

```console
research-retriever harvest-references "doi:10.1234/example"
```

Check for a preprint's published version:

```console
research-retriever check-versions "doi:10.1234/example"
```

Reconcile conservative preprint/publication matches already present in the catalog:

```console
research-retriever reconcile-versions
```

Set read state using a DOI, citation key, Zotero item key, or catalog key:

```console
research-retriever status "ABCD1234" read
```

Citation keys are imported as convenient, case-insensitive lookup aliases and written to Obsidian
frontmatter. They are not used as canonical paper identities because Zotero or Better BibTeX may
regenerate them when metadata changes. Run `research-retriever sync --full` once after enabling this
feature to populate keys for papers already in the local catalog.

Force a refreshed analysis and note:

```console
research-retriever analyze "doi:10.1234/example"
```

## Automatic full-text retrieval

Research Retriever creates Zotero items through the Web API, which cannot invoke Zotero Desktop's
**Find Available PDF** command. The optional companion plugin watches newly added items carrying the
`rr:managed` tag and asks Zotero Desktop to find available files after they sync locally.

Build the plugin:

```console
python scripts/build_zotero_plugin.py
```

In Zotero, open **Tools → Plugins**, choose **Install Plugin From File**, and select:

```text
dist/research-retriever-full-text.xpi
```

Keep Zotero running or open it later and allow synchronization to complete. The plugin processes only
new Research Retriever items, batches items arriving in the same sync, and skips records that already
have a PDF. It does not read or submit school credentials.

Zotero's retrieval can use open-access sources and direct institutional access available to the
desktop application. Campus-network or system-wide VPN access generally works; browser-only proxy
sessions may not. Retrieval success also depends on the DOI/URL, publisher, resolver, and rate limits.

Commands return a non-zero status on configuration, connectivity, or write failures, making them
suitable for `launchd`, cron, or another scheduler. Phase one does not install a scheduler itself.

## Obsidian note safety

A generated note contains managed properties, a generated block, and an unrestricted section:

```markdown
---
zotero_key: "ABCD1234"
reading_status: "unread"
---

<!-- research-retriever:generated:start -->
Generated analysis and synchronized metadata
<!-- research-retriever:generated:end -->

## My notes

Anything written here is preserved.
```

Unknown frontmatter properties are also preserved. `reading_status` is a deliberately shared field:
changing it to a valid value in Obsidian is picked up when that note is next processed and is written
back to the corresponding Zotero status tag.

## Important limitations

- OpenAlex and Crossref reference deposits can be incomplete. The tool preserves unresolved deposited
  citations instead of silently claiming the harvested list is exhaustive.
- A journal venue does not prove that a particular item was peer reviewed. Journal articles are
  labeled `likely_peer_reviewed`; preprints are `not_peer_reviewed`; conference review is `varies`.
- Inferred version relationships require an identical normalized title, overlapping authors, and a
  preprint-versus-published type pairing. Near-title fuzzy matching is not used because false
  preprint/publication matches are worse than a missed suggestion. Notes distinguish verified
  metadata from inferred matches.
- Phase one analyzes abstracts unless a full-text source is explicitly supplied by a future retrieval
  adapter. Every note records its analysis basis.
- Institutional SSO, licensed PDF retrieval, Consensus/SciSpace enrichment, audio, podcasts, and a
  private podcast feed are later phases.
- The tool does not bypass paywalls, MFA, CAPTCHAs, or publisher download limits.

## Development checks

```console
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider
python -m ruff check .
python -m ruff format --check .
```
