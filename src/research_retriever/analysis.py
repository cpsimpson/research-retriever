"""Structured paper analysis with an optional OpenAI Responses API adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from research_retriever.http import JsonHttpClient
from research_retriever.models import Paper


@dataclass(slots=True)
class PaperAnalysis:
    summary: str
    methods: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    why_interesting: str = ""
    limitations: list[str] = field(default_factory=list)
    basis: str = "abstract_only"
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PaperAnalysis:
        return cls(**value)


class Analyzer(Protocol):
    def analyze(
        self, paper: Paper, research_interest: str, source_text: str | None = None
    ) -> PaperAnalysis:
        """Analyze a paper using only the supplied source material."""


class PendingAnalyzer:
    def analyze(
        self, paper: Paper, research_interest: str, source_text: str | None = None
    ) -> PaperAnalysis:
        basis = "full_text" if source_text else "abstract_only"
        return PaperAnalysis(
            summary=(
                "Analysis pending. Configure an analysis provider to generate a grounded summary."
            ),
            why_interesting=(
                f"This paper matched the configured research interest: {research_interest}"
                if research_interest
                else "No research-interest profile was supplied."
            ),
            limitations=[
                "No AI analysis was run.",
                "Bibliographic metadata should not be treated as evidence for methods or findings.",
            ],
            basis=basis,
            confidence="not_assessed",
        )


class OpenAIAnalyzer:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        api_key: str,
        model: str,
        client: JsonHttpClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("An OpenAI API key is required")
        if not model:
            raise ValueError("An OpenAI model is required")
        self.model = model
        self.client = client or JsonHttpClient(
            user_agent="research-retriever/0.1",
            timeout=90,
            default_headers={"Authorization": f"Bearer {api_key}"},
        )

    def analyze(
        self, paper: Paper, research_interest: str, source_text: str | None = None
    ) -> PaperAnalysis:
        material = source_text or paper.abstract
        if not material:
            return PendingAnalyzer().analyze(paper, research_interest, source_text)
        basis = "full_text" if source_text else "abstract_only"
        payload = {
            "model": self.model,
            "store": False,
            "reasoning": {"effort": "low"},
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Analyze research papers conservatively. Use only the supplied "
                        "source text. Do not infer methods, findings, sample characteristics, "
                        "or causal claims that "
                        "are not explicit. Put missing or uncertain information in limitations."
                    ),
                },
                {
                    "role": "user",
                    "content": _analysis_prompt(paper, research_interest, material, basis),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "paper_analysis",
                    "strict": True,
                    "schema": ANALYSIS_SCHEMA,
                }
            },
        }
        response = self.client.request_json("POST", self.endpoint, payload)
        parsed = json.loads(_response_text(response))
        parsed["basis"] = basis
        return PaperAnalysis.from_dict(parsed)


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "methods": {"type": "array", "items": {"type": "string"}},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "why_interesting": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "basis": {"type": "string", "enum": ["abstract_only", "full_text"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "summary",
        "methods",
        "key_findings",
        "why_interesting",
        "limitations",
        "basis",
        "confidence",
    ],
    "additionalProperties": False,
}


def analysis_for(paper: Paper) -> PaperAnalysis | None:
    raw = paper.metadata.get("analysis")
    return PaperAnalysis.from_dict(raw) if isinstance(raw, dict) else None


def attach_analysis(paper: Paper, analysis: PaperAnalysis) -> None:
    paper.metadata["analysis"] = analysis.to_dict()


def _analysis_prompt(paper: Paper, interest: str, material: str, basis: str) -> str:
    return f"""Paper title: {paper.title}
Publication type: {paper.work_type.value}
Review status: {paper.review_status.value}
Analysis basis: {basis}
Researcher's interest: {interest or "Not specified"}

Source text:
{material}

Return a short summary, explicitly stated methods, key findings, why the paper may matter to the
research interest, material limitations of this analysis, and a confidence level. When the source is
only an abstract, say so in limitations and do not imply that the full paper was reviewed.
"""


def _response_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise RuntimeError(f"Analysis request was refused: {content.get('refusal', '')}")
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise RuntimeError("Analysis provider returned no structured text output")
