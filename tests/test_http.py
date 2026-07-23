from __future__ import annotations

import io
import urllib.error

import pytest

from research_retriever.http import HttpError, JsonHttpClient


def test_http_error_reports_method_without_masking_response(monkeypatch) -> None:
    error = urllib.error.HTTPError(
        "https://example.test/resource",
        403,
        "Forbidden",
        {},
        io.BytesIO(b"access denied"),
    )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(HttpError, match=r"GET .*: 403 access denied"):
        JsonHttpClient("test", max_attempts=1).get("https://example.test/resource")


def test_network_error_reports_request_method(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(HttpError, match=r"POST .*: offline"):
        JsonHttpClient("test", max_attempts=1).request_json(
            "POST", "https://example.test/resource", {"value": 1}
        )


def test_http_errors_redact_api_keys_from_urls(monkeypatch) -> None:
    error = urllib.error.HTTPError(
        "https://example.test/resource",
        400,
        "Bad Request",
        {},
        io.BytesIO(b"invalid API key super-secret"),
    )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(HttpError) as captured:
        JsonHttpClient("test", max_attempts=1).get(
            "https://example.test/resource", {"api_key": "super-secret", "search": "topic"}
        )

    assert "super-secret" not in str(captured.value)
    assert "api_key=%5BREDACTED%5D" in str(captured.value)
    assert "invalid API key [REDACTED]" in str(captured.value)


def test_timeout_reports_endpoint_and_duration(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(HttpError, match=r"GET https://example\.test/resource: timed out after 12"):
        JsonHttpClient("test", timeout=12, max_attempts=1).get("https://example.test/resource")
