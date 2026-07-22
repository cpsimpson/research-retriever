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
