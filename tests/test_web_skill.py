"""Tests for chika/skills/web_skill/__init__.py."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from chika.skills.web_skill import _simplify_query, web_search


class TestSimplifyQuery:
    def test_strips_site_filter(self):
        result = _simplify_query("python tutorials site:stackoverflow.com")
        assert result == "python tutorials"

    def test_strips_filetype_filter(self):
        result = _simplify_query("report filetype:pdf")
        assert result == "report"

    def test_strips_inurl_filter(self):
        result = _simplify_query("news inurl:blog something")
        assert result is not None
        assert "inurl:" not in result

    def test_strips_boolean_operators(self):
        result = _simplify_query("cats OR dogs")
        assert result is not None
        assert " OR " not in result

    def test_returns_none_when_nothing_to_strip(self):
        result = _simplify_query("simple query")
        assert result is None

    def test_returns_none_when_simplified_equals_original(self):
        result = _simplify_query("python")
        assert result is None

    def test_returns_none_when_empty_after_strip(self):
        result = _simplify_query("site:example.com")
        assert result is None


class TestWebSearch:
    def _make_ddgs(self, results):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = results
        mock_ddgs_instance.__enter__ = MagicMock(return_value=mock_ddgs_instance)
        mock_ddgs_instance.__exit__ = MagicMock(return_value=False)
        mock_ddgs_class = MagicMock(return_value=mock_ddgs_instance)
        return mock_ddgs_class

    def test_returns_results(self):
        fake_results = [
            {"title": "Result 1", "href": "http://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "http://example.com/2", "body": "Snippet 2"},
        ]
        mock_ddgs = self._make_ddgs(fake_results)
        with patch("ddgs.DDGS", mock_ddgs):
            result = asyncio.run(web_search("test query"))
        assert result["_source"] == "web_search"
        assert result["count"] == 2
        assert result["query"] == "test query"
        assert result["results"][0]["title"] == "Result 1"
        assert result["results"][0]["url"] == "http://example.com/1"
        assert result["results"][0]["snippet"] == "Snippet 1"

    def test_has_grounding_field(self):
        fake_results = [{"title": "T", "href": "http://x.com", "body": "S"}]
        mock_ddgs = self._make_ddgs(fake_results)
        with patch("ddgs.DDGS", mock_ddgs):
            result = asyncio.run(web_search("test"))
        assert "_grounding" in result

    def test_empty_results_returns_count_zero(self):
        mock_ddgs = self._make_ddgs([])
        with patch("ddgs.DDGS", mock_ddgs):
            result = asyncio.run(web_search("simple query no filters"))
        assert result["count"] == 0
        assert result["results"] == []

    def test_retry_with_simplified_query_on_no_results(self):
        fake_results = [{"title": "R", "href": "http://x.com", "body": "S"}]

        call_count = 0
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)

        def text_side_effect(query, max_results=8):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return fake_results

        mock_instance.text.side_effect = text_side_effect
        mock_ddgs_class = MagicMock(return_value=mock_instance)

        with patch("ddgs.DDGS", mock_ddgs_class):
            result = asyncio.run(web_search("python site:stackoverflow.com"))

        assert result["count"] == 1
        assert "original_query" in result
        assert "retry_reason" in result

    def test_exception_returns_error_dict(self):
        mock_ddgs_class = MagicMock(side_effect=Exception("network error"))
        with patch("ddgs.DDGS", mock_ddgs_class):
            result = asyncio.run(web_search("test"))
        assert "error" in result
        assert result["_source"] == "web_search"
        assert result["count"] == 0

    def test_max_results_parameter(self):
        fake_results = [{"title": "T", "href": "http://x.com", "body": "S"}]
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = fake_results
        mock_ddgs_class = MagicMock(return_value=mock_instance)

        with patch("ddgs.DDGS", mock_ddgs_class):
            asyncio.run(web_search("test", max_results=3))

        mock_instance.text.assert_called_once_with("test", max_results=3)
