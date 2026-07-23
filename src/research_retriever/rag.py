"""Adapter for the existing zotero-LLM local RAG application."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence

from research_retriever.settings import RagSettings


class RagClient:
    def __init__(
        self,
        settings: RagSettings,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.settings = settings
        self.runner = runner

    def available(self) -> bool:
        executable = shlex.split(self.settings.command)[0]
        return bool(shutil.which(executable))

    def ingest(self) -> None:
        self._run(
            [
                "ingest",
                "--source",
                str(self.settings.source_dir),
                "--parsed-out",
                str(self.settings.parsed_text_dir),
                "--qdrant-path",
                str(self.settings.qdrant_path),
                "--collection",
                self.settings.collection,
                "--embedding-model",
                self.settings.embedding_model,
                "--ollama-host",
                self.settings.ollama_host,
                *self._qdrant_args(),
            ]
        )

    def search(self, query: str, limit: int) -> None:
        self._run(
            [
                "search",
                query,
                "--qdrant-path",
                str(self.settings.qdrant_path),
                "--collection",
                self.settings.collection,
                "--embedding-model",
                self.settings.embedding_model,
                "--ollama-host",
                self.settings.ollama_host,
                "--limit",
                str(limit),
                *self._qdrant_args(),
            ]
        )

    def ask(self, question: str, limit: int) -> None:
        self._run(
            [
                "ask",
                question,
                "--qdrant-path",
                str(self.settings.qdrant_path),
                "--collection",
                self.settings.collection,
                "--embedding-model",
                self.settings.embedding_model,
                "--chat-model",
                self.settings.chat_model,
                "--ollama-host",
                self.settings.ollama_host,
                "--limit",
                str(limit),
                *self._qdrant_args(),
            ]
        )

    def _qdrant_args(self) -> list[str]:
        return ["--qdrant-url", self.settings.qdrant_url]

    def _run(self, arguments: Sequence[str]) -> None:
        if not self.settings.enabled:
            raise RuntimeError("Enable [rag] in the Research Retriever configuration")
        command = [*shlex.split(self.settings.command), *arguments]
        try:
            self.runner(command, check=True)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"zotero-LLM command was not found: {shlex.split(self.settings.command)[0]}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"zotero-LLM exited with status {exc.returncode}") from exc
