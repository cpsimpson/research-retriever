"""Small JSON HTTP client with polite identification and bounded retries."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class HttpError(RuntimeError):
    pass


@dataclass(slots=True)
class JsonHttpClient:
    user_agent: str
    timeout: float = 30.0
    max_attempts: int = 3
    default_headers: dict[str, str] = field(default_factory=dict)

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}, doseq=True
            )
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        request = urllib.request.Request(url, headers=self._headers())
        return self._send(request)

    def request_json(
        self,
        method: str,
        url: str,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request_headers = self._headers()
        request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        return self._send(request)

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": self.user_agent, **self.default_headers}

    def _send(self, request: urllib.request.Request) -> Any:
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                retryable = exc.code in {429, 500, 502, 503, 504}
                if not retryable or attempt == self.max_attempts - 1:
                    detail = exc.read().decode(errors="replace")[:500]
                    raise HttpError(f"{request.method} {request.full_url}: {exc.code} {detail}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(delay, 30))
            except urllib.error.URLError as exc:
                if attempt == self.max_attempts - 1:
                    raise HttpError(f"{request.method} {request.full_url}: {exc.reason}") from exc
                time.sleep(2**attempt)
        raise AssertionError("unreachable")
