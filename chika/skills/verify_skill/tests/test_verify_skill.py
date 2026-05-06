"""Tests for chika/skills/verify_skill/__init__.py."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from chika.core.variable_store import VariableStore
from chika.skills.verify_skill import _make_fact_check, verify_url, web_fetch


def _make_mock_response(status=200, content_type="text/html", text="<html>body</html>",
                        url="http://example.com", content=b"<html>body</html>"):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    resp.text = text
    resp.url = url
    resp.content = content
    return resp


def _make_async_client(response):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    client.head = AsyncMock(return_value=response)
    return client


class TestWebFetch:
    def test_successful_fetch(self):
        resp = _make_mock_response(status=200, content_type="text/html", text="Hello page")
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://example.com"))
        assert result["_source"] == "web_fetch"
        assert result["status"] == 200
        assert result["content"] == "Hello page"
        assert result["truncated"] is False

    def test_truncates_large_body(self):
        big_text = "x" * 30000
        resp = _make_mock_response(text=big_text, content=big_text.encode())
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://example.com", max_chars=100))
        assert result["truncated"] is True
        assert len(result["content"]) == 100

    def test_binary_content_returns_hint(self):
        resp = _make_mock_response(content_type="image/png", text="", content=b"\x89PNG")
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://example.com/image.png"))
        assert "binary content" in result["content"]

    def test_exception_returns_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://bad.example.com"))
        assert "error" in result
        assert result["_source"] == "web_fetch"

    def test_json_content_type_returned(self):
        resp = _make_mock_response(content_type="application/json", text='{"key": "val"}',
                                   content=b'{"key": "val"}')
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://api.example.com"))
        assert result["content"] == '{"key": "val"}'

    def test_ignored_kwargs_accepted(self, tmp_path):
        resp = _make_mock_response()
        mock_client = _make_async_client(resp)
        # tmp_path keeps the path platform-portable AND avoids
        # bandit's hardcoded-/tmp/ warning. The httpx client is
        # mocked so no file is actually written either way.
        save_path = tmp_path / "x.html"
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(web_fetch("http://example.com", save_path=str(save_path)))
        assert result["_source"] == "web_fetch"


class TestVerifyUrl:
    def test_successful_head(self):
        resp = _make_mock_response(status=200, content_type="text/html",
                                   url="http://example.com")
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://example.com"))
        assert result["reachable"] is True
        assert result["status"] == 200
        assert result["is_html"] is True
        assert result["_source"] == "verify_url"

    def test_405_falls_back_to_get(self):
        head_resp = _make_mock_response(status=405, content_type="text/html")
        get_resp = _make_mock_response(status=200, content_type="text/html")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.head = AsyncMock(return_value=head_resp)
        mock_client.get = AsyncMock(return_value=get_resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://example.com"))
        assert result["reachable"] is True
        mock_client.get.assert_called_once()

    def test_image_url_detected(self):
        resp = _make_mock_response(status=200, content_type="image/jpeg")
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://example.com/photo.jpg"))
        assert result["is_image"] is True
        assert result["is_html"] is False

    def test_unreachable_returns_false(self):
        resp = _make_mock_response(status=404)
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://example.com/missing"))
        assert result["reachable"] is False

    def test_exception_returns_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://bad.example.com"))
        assert result["reachable"] is False
        assert "error" in result

    def test_redirect_detected(self):
        resp = _make_mock_response(status=200, url="http://www.example.com")
        mock_client = _make_async_client(resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(verify_url("http://example.com"))
        assert result["redirected"] is True


class TestFactCheck:
    def setup_method(self):
        self.store = VariableStore()
        self.fact_check = _make_fact_check(self.store)

    def test_empty_ledger_returns_not_supported(self):
        result = asyncio.run(self.fact_check("Paris is in France"))
        assert result["supported"] is False
        assert result["reason"] == "ledger_empty"
        assert "directive" in result

    def test_matching_fact_returns_supported(self):
        facts = [
            {"snippet": "Paris is the capital of France", "url": "http://example.com",
             "title": "France", "query": "capital France", "_source": "web_search"},
        ]
        self.store.set("facts", facts)
        result = asyncio.run(self.fact_check("Paris is capital France"))
        assert result["supported"] is True
        assert len(result["matches"]) >= 1

    def test_no_matching_fact_returns_not_supported(self):
        facts = [
            {"snippet": "Pizza was invented in Naples", "url": "http://example.com",
             "title": "Pizza", "query": "pizza origin", "_source": "web_search"},
        ]
        self.store.set("facts", facts)
        result = asyncio.run(self.fact_check("Quantum computing is powerful"))
        assert result["supported"] is False
        assert result["reason"] == "no_matching_fact_in_ledger"

    def test_facts_not_list_treated_as_empty(self):
        self.store.set("facts", "not a list")
        result = asyncio.run(self.fact_check("some claim"))
        assert result["supported"] is False
        assert result["reason"] == "ledger_empty"
