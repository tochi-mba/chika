"""Tests for config._int_env helper."""
from __future__ import annotations

import os
from unittest.mock import patch


class TestIntEnv:
    def test_returns_default_when_key_absent(self):
        from config import _int_env
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("_CHIKA_TEST_INT", None)
            assert _int_env("_CHIKA_TEST_INT", 42) == 42

    def test_parses_valid_integer(self):
        from config import _int_env
        with patch.dict(os.environ, {"_CHIKA_TEST_INT": "7"}):
            assert _int_env("_CHIKA_TEST_INT", 42) == 7

    def test_falls_back_on_non_numeric(self):
        from config import _int_env
        with patch.dict(os.environ, {"_CHIKA_TEST_INT": "not_a_number"}):
            assert _int_env("_CHIKA_TEST_INT", 99) == 99

    def test_falls_back_on_empty_string(self):
        from config import _int_env
        with patch.dict(os.environ, {"_CHIKA_TEST_INT": ""}):
            assert _int_env("_CHIKA_TEST_INT", 5) == 5
