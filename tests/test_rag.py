from pathlib import Path

import pytest

from research_retriever.rag import RagClient
from research_retriever.settings import RagSettings


class Runner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, check):
        assert check is True
        self.commands.append(command)


def settings(**overrides) -> RagSettings:
    values = {
        "enabled": True,
        "command": "/opt/zotero-llm",
        "source_dir": Path("/zotero/storage"),
        "parsed_text_dir": Path("/state/text"),
        "qdrant_path": Path("/state/qdrant"),
        "qdrant_url": "http://127.0.0.1:6333",
        "collection": "papers",
        "embedding_model": "embed",
        "chat_model": "chat",
        "ollama_host": "http://127.0.0.1:11434",
    }
    values.update(overrides)
    return RagSettings(**values)


def test_rag_adapter_invokes_existing_ingest_with_explicit_configuration() -> None:
    runner = Runner()
    RagClient(settings(), runner=runner).ingest()
    command = runner.commands[0]
    assert command[:2] == ["/opt/zotero-llm", "ingest"]
    assert command[command.index("--source") + 1] == "/zotero/storage"
    assert command[command.index("--collection") + 1] == "papers"
    assert command[command.index("--qdrant-url") + 1] == "http://127.0.0.1:6333"


def test_rag_adapter_invokes_search_and_ask() -> None:
    runner = Runner()
    rag = RagClient(settings(), runner=runner)
    rag.search("mental states", 4)
    rag.ask("What methods were used?", 6)
    assert runner.commands[0][1:3] == ["search", "mental states"]
    assert runner.commands[0][-2:] == ["--qdrant-url", "http://127.0.0.1:6333"]
    assert runner.commands[1][1:3] == ["ask", "What methods were used?"]
    assert "chat" in runner.commands[1]


def test_rag_adapter_requires_explicit_enablement() -> None:
    with pytest.raises(RuntimeError, match=r"Enable \[rag\]"):
        RagClient(settings(enabled=False), runner=Runner()).ingest()
