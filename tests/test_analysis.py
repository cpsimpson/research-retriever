import json

import pytest

from research_retriever.analysis import OllamaAnalyzer, OpenAIAnalyzer, PendingAnalyzer
from research_retriever.models import Paper


class FakeClient:
    def __init__(self):
        self.payload = None

    def request_json(self, _method, _url, payload):
        self.payload = payload
        result = {
            "summary": "A grounded summary.",
            "methods": ["Survey"],
            "key_findings": ["A stated finding"],
            "why_interesting": "It matches the topic.",
            "limitations": ["Abstract only"],
            "basis": "abstract_only",
            "confidence": "medium",
        }
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(result)}],
                }
            ]
        }


class FakeOllamaClient:
    def __init__(self):
        self.payload = None

    def get(self, _url):
        return {"models": [{"name": "local-model"}]}

    def request_json(self, _method, _url, payload):
        self.payload = payload
        result = {
            "summary": "A local summary.",
            "methods": ["Experiment"],
            "key_findings": ["A reported result"],
            "why_interesting": "It matches the topic.",
            "limitations": ["Abstract only"],
            "basis": "abstract_only",
            "confidence": "medium",
        }
        return {"message": {"role": "assistant", "content": json.dumps(result)}}


def test_pending_analysis_does_not_invent_findings() -> None:
    result = PendingAnalyzer().analyze(Paper(title="No abstract"), "A topic")
    assert result.methods == []
    assert result.key_findings == []
    assert result.confidence == "not_assessed"


def test_openai_analysis_uses_structured_output_and_disables_storage() -> None:
    client = FakeClient()
    result = OpenAIAnalyzer("secret", "test-model", client=client).analyze(
        Paper(title="Paper", abstract="The authors used a survey."), "Survey research"
    )
    assert result.methods == ["Survey"]
    assert client.payload["store"] is False
    assert client.payload["text"]["format"]["strict"] is True


def test_ollama_analysis_uses_local_structured_output() -> None:
    client = FakeOllamaClient()
    analyzer = OllamaAnalyzer("local-model", client=client)
    analyzer.validate_model()

    result = analyzer.analyze(
        Paper(title="Paper", abstract="The authors ran an experiment."),
        "Experimental research",
    )

    assert result.methods == ["Experiment"]
    assert client.payload["stream"] is False
    assert client.payload["think"] is False
    assert client.payload["format"]["additionalProperties"] is False
    assert client.payload["options"]["temperature"] == 0


def test_ollama_validation_reports_missing_model() -> None:
    analyzer = OllamaAnalyzer("missing-model", client=FakeOllamaClient())

    with pytest.raises(RuntimeError, match="missing-model.*not installed"):
        analyzer.validate_model()
