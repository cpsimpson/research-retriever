"""Build the Zotero companion plugin as an installable XPI archive."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build(destination: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    source = root / "zotero-plugin"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    return destination


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = build(root / "dist" / "research-retriever-full-text.xpi")
    print(destination)


if __name__ == "__main__":
    main()
