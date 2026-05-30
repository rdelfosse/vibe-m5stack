"""
Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
Copyright 2026 Romain Delfosse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
""""""Tests for SessionManager from plugin.m5stack_utils."""

import pytest
from plugin.m5stack_utils import SessionManager


class TestSessionManagerFormatTitle:
    """Tests for SessionManager.format_title()."""

    def test_format_title_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("VIBE_SESSION_NAME", "alpha")
        sm = SessionManager()
        assert sm.format_title("hello") == "[alpha] hello"

    def test_format_title_truncates_name_to_12(self, monkeypatch):
        monkeypatch.setenv("VIBE_SESSION_NAME", "a-very-long-session-name")
        sm = SessionManager()
        result = sm.format_title("x")
        # Name should be truncated to 12 chars
        assert result.startswith("[a-very-long-")
        assert len(result.split("]")[0]) <= 13  # [ + 12 chars max

    def test_format_title_uuid_fallback(self, monkeypatch):
        monkeypatch.delenv("VIBE_SESSION_NAME", raising=False)
        sm = SessionManager()
        title = sm.format_title("hi")
        assert title.startswith("[")
        assert "] hi" in title
        # UUID should be 8 chars
        session_part = title.split("]")[0][1:]
        assert len(session_part) == 8

    def test_format_title_truncates_total_length(self, monkeypatch):
        """Test that total title length is limited (30 - len(session) - 3)."""
        monkeypatch.setenv("VIBE_SESSION_NAME", "test")
        sm = SessionManager()
        # Very long title should be truncated
        long_title = "x" * 100
        result = sm.format_title(long_title)
        # Session name "test" = 4 chars, so [test] = 7 chars with brackets
        # Remaining for title: 30 - 4 - 3 = 23 chars
        # So total should be <= 7 + 23 = 30
        assert len(result) <= 30

    def test_set_session_name_priority_over_env(self, monkeypatch):
        monkeypatch.setenv("VIBE_SESSION_NAME", "from_env")
        sm = SessionManager()
        sm.session_name = "from_setter"
        result = sm.format_title("test")
        assert result.startswith("[from_setter]")


class TestSessionManagerStrictMode:
    """Tests for SessionManager.is_strict_mode."""

    def test_strict_mode_default_false(self, monkeypatch):
        monkeypatch.delenv("VIBE_M5STACK_STRICT", raising=False)
        sm = SessionManager()
        assert sm.is_strict_mode is False

    def test_strict_mode_true_when_env_true(self, monkeypatch):
        monkeypatch.setenv("VIBE_M5STACK_STRICT", "true")
        sm = SessionManager()
        assert sm.is_strict_mode is True

    def test_strict_mode_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("VIBE_M5STACK_STRICT", "TRUE")
        sm = SessionManager()
        assert sm.is_strict_mode is True

    def test_strict_mode_false_when_env_false(self, monkeypatch):
        monkeypatch.setenv("VIBE_M5STACK_STRICT", "false")
        sm = SessionManager()
        assert sm.is_strict_mode is False


class TestSessionManagerConfig:
    """Tests for SessionManager configuration properties."""

    def test_max_retries_default(self, monkeypatch):
        monkeypatch.delenv("VIBE_M5STACK_MAX_RETRIES", raising=False)
        sm = SessionManager()
        assert sm.max_retries == 10

    def test_max_retries_from_env(self, monkeypatch):
        monkeypatch.setenv("VIBE_M5STACK_MAX_RETRIES", "5")
        sm = SessionManager()
        assert sm.max_retries == 5

    def test_retry_delay_default(self, monkeypatch):
        monkeypatch.delenv("VIBE_M5STACK_RETRY_DELAY", raising=False)
        sm = SessionManager()
        assert sm.retry_delay == 2.0

    def test_retry_delay_from_env(self, monkeypatch):
        monkeypatch.setenv("VIBE_M5STACK_RETRY_DELAY", "0.5")
        sm = SessionManager()
        assert sm.retry_delay == 0.5
