from __future__ import annotations

import urllib.error
import io
import zipfile

import pytest

from python.etl import fetch_tepco


class _MockResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.test/tepco.zip",
        code,
        "error",
        hdrs=None,
        fp=None,
    )


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("20260525_power_usage.csv", "DATE,TIME,POWER\n")
    return buffer.getvalue()


def test_open_with_retry_uses_browser_headers(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _MockResponse(b"zip")

    monkeypatch.setattr(fetch_tepco.urllib.request, "urlopen", fake_urlopen)

    with fetch_tepco._open_with_retry("https://example.test/tepco.zip") as response:
        assert response.read() == b"zip"

    request, timeout = requests[0]
    assert timeout == fetch_tepco._HTTP_TIMEOUT_SECONDS
    assert "Mozilla/5.0" in request.headers["User-agent"]
    assert request.headers["Referer"] == "https://www.tepco.co.jp/forecast/"


def test_open_with_retry_retries_transient_http(monkeypatch):
    calls = []
    responses = [
        _http_error(403),
        _MockResponse(b"zip"),
    ]

    def fake_urlopen(request, timeout):
        calls.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(fetch_tepco.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fetch_tepco.time, "sleep", lambda seconds: None)

    with fetch_tepco._open_with_retry("https://example.test/tepco.zip") as response:
        assert response.read() == b"zip"

    assert len(calls) == 2


def test_fetch_month_uses_curl_fallback_after_forbidden(monkeypatch, tmp_path):
    def fake_open_with_retry(url):
        raise _http_error(403)

    monkeypatch.setattr(fetch_tepco, "_open_with_retry", fake_open_with_retry)
    monkeypatch.setattr(fetch_tepco, "_download_with_curl", lambda url: _zip_bytes())

    assert fetch_tepco.fetch_month("202605", tmp_path) == 1
    assert (
        tmp_path / "2026" / "202605_power_usage" / "20260525_power_usage.csv"
    ).exists()


def test_fetch_month_fails_after_forbidden_when_curl_fails(monkeypatch, tmp_path):
    def fake_open_with_retry(url):
        raise _http_error(403)

    def fake_download_with_curl(url):
        raise FileNotFoundError("curl")

    monkeypatch.setattr(fetch_tepco, "_open_with_retry", fake_open_with_retry)
    monkeypatch.setattr(fetch_tepco, "_download_with_curl", fake_download_with_curl)

    with pytest.raises(RuntimeError):
        fetch_tepco.fetch_month("202605", tmp_path)


def test_fetch_month_still_skips_not_found(monkeypatch, tmp_path):
    def fake_open_with_retry(url):
        raise _http_error(404)

    monkeypatch.setattr(fetch_tepco, "_open_with_retry", fake_open_with_retry)

    assert fetch_tepco.fetch_month("202605", tmp_path) == 0
