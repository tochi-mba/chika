"""Tests for chika/tools/web_fetch_tool.py."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chika.tools.web_fetch_tool import web_fetch, web_head, WEB_FETCH_TOOLS


def run(coro):
    return asyncio.run(coro)


def _make_response(status=200, content_type="text/html; charset=utf-8",
                   text="<html>hello</html>", url="http://example.com",
                   content=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    resp.text = text
    resp.url = url
    resp.content = content if content is not None else text.encode("utf-8")
    return resp


class TestWebFetch:
    def test_successful_text_fetch(self):
        resp = _make_response(status=200, text="Hello page")
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com"))
        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["text"] == "Hello page"

    def test_non_200_returns_error(self):
        resp = _make_response(status=404, text="Not Found")
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com/missing"))
        assert result["ok"] is False
        assert "error" in result
        assert "404" in result["error"]

    def test_binary_content_without_save_path(self):
        resp = _make_response(content_type="image/png", text="", content=b"\x89PNG")
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com/image.png"))
        assert result.get("binary") is True
        assert "save_path" in result.get("hint", "")

    def test_save_to_file(self, tmp_path):
        resp = _make_response(status=200, text="page content")
        save_path = str(tmp_path / "page.html")
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com", save_path=save_path))
        assert result["saved_to"] == save_path
        assert Path(save_path).read_bytes() == b"page content"

    def test_save_path_traversal_rejected(self):
        resp = _make_response()
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com", save_path="../../../etc/passwd"))
        assert "error" in result
        assert "traversal" in result["error"]

    def test_large_text_truncated(self):
        big_text = "x" * 3000000
        resp = _make_response(text=big_text, content=big_text.encode())
        with patch("requests.get", return_value=resp):
            result = run(web_fetch("http://example.com", max_size_kb=1))
        assert result.get("truncated") is True
        assert len(result["text"]) < len(big_text)

    def test_timeout_exception(self):
        import requests as _requests
        with patch("requests.get", side_effect=_requests.exceptions.Timeout()):
            result = run(web_fetch("http://example.com"))
        assert "error" in result
        assert "timed out" in result["error"]

    def test_connection_error(self):
        import requests as _requests
        with patch("requests.get", side_effect=_requests.exceptions.ConnectionError("refused")):
            result = run(web_fetch("http://example.com"))
        assert "error" in result
        assert "Connection failed" in result["error"]

    def test_generic_exception(self):
        with patch("requests.get", side_effect=Exception("unexpected")):
            result = run(web_fetch("http://example.com"))
        assert "error" in result


class TestWebHead:
    def test_successful_head(self):
        resp = _make_response(status=200, content_type="text/html", url="http://example.com")
        with patch("requests.head", return_value=resp):
            result = run(web_head("http://example.com"))
        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["is_html"] is True
        assert result["is_image"] is False

    def test_image_url(self):
        resp = _make_response(status=200, content_type="image/jpeg")
        with patch("requests.head", return_value=resp):
            result = run(web_head("http://example.com/photo.jpg"))
        assert result["is_image"] is True
        assert result["is_html"] is False

    def test_exception_returns_error(self):
        with patch("requests.head", side_effect=Exception("timeout")):
            result = run(web_head("http://example.com"))
        assert "error" in result
        assert result["ok"] is False


class TestToolDefinitions:
    def test_two_tools_registered(self):
        assert len(WEB_FETCH_TOOLS) == 2

    def test_tool_names(self):
        names = [t.name for t in WEB_FETCH_TOOLS]
        assert "web_fetch" in names
        assert "web_head" in names
