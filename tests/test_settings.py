from pathlib import Path

from research_retriever.settings import load_settings


def test_settings_load_topics_and_secret_names(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'''[app]
vault_path = "{tmp_path}/vault"
state_path = "{tmp_path}/catalog.sqlite3"
[zotero]
library_id = "123"
[providers]
email = "researcher@example.test"
[[topics]]
id = "topic"
name = "Topic"
query = "How does the topic work?"
interest = "It matters"
'''
    )
    monkeypatch.setenv("ZOTERO_API_KEY", "secret")
    settings = load_settings(config)
    assert settings.app.vault_path == Path(tmp_path / "vault")
    assert settings.zotero.api_key == "secret"
    assert settings.topics[0].query == "How does the topic work?"

