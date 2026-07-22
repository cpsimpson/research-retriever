import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_is_scoped_to_managed_items_and_current_zotero_versions() -> None:
    manifest = json.loads((ROOT / "zotero-plugin" / "manifest.json").read_text())
    zotero = manifest["applications"]["zotero"]
    bootstrap = (ROOT / "zotero-plugin" / "bootstrap.js").read_text()

    assert zotero["strict_min_version"] == "7.0"
    assert zotero["strict_max_version"] == "10.0.*"
    assert 'tag === "rr:managed"' in bootstrap
    assert "addAvailableFiles(eligible)" in bootstrap
    assert 'event !== "add"' in bootstrap
    assert 'attachmentContentType === "application/pdf"' in bootstrap


def test_plugin_build_contains_only_runtime_files(tmp_path) -> None:
    from scripts.build_zotero_plugin import build

    artifact = build(tmp_path / "research-retriever-full-text.xpi")
    with ZipFile(artifact) as archive:
        assert sorted(archive.namelist()) == ["bootstrap.js", "manifest.json"]
