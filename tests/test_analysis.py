import json

from research_retriever.analysis import OpenAIAnalyzer, PendingAnalyzer
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
