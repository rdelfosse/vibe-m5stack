"""Tests for format_tool_info from plugin.vibe_m5stack_hook."""

import sys
from unittest.mock import MagicMock
from pydantic import BaseModel

# Stub modules BEFORE importing vibe_m5stack_hook to prevent side effects
# The hook does install_hook() at module load which patches AgentLoop
stub_types = MagicMock()
stub_types.ApprovalResponse = MagicMock()
stub_permissions = MagicMock()
stub_agent_loop = MagicMock()

sys.modules["vibe.core.types"] = stub_types
sys.modules["vibe.core.tools.permissions"] = stub_permissions
sys.modules["vibe.core.agent_loop"] = stub_agent_loop

# Now we can safely import the function
from plugin.vibe_m5stack_hook import format_tool_info


class FakeArgs(BaseModel):
    """Fake args model for testing.
    
    Uses model_dump(exclude_none=True) by default to avoid None values in dict.
    """
    path: str | None = None
    content: str | None = None
    command: str | None = None
    file_path: str | None = None
    
    def model_dump(self, **kwargs):
        # Exclude None values by default to match Pydantic v2 behavior
        kwargs.setdefault('exclude_none', True)
        return super().model_dump(**kwargs)


class TestFormatToolInfo:
    """Tests for format_tool_info function."""

    def test_format_extracts_path(self):
        args = FakeArgs(path="/tmp/foo.py")
        title, body = format_tool_info("write_file", args)
        assert "write_file" in title
        assert "/tmp/foo.py" in body

    def test_format_truncates_long_path(self):
        args = FakeArgs(path="/very/long/path/" + "x" * 200)
        title, body = format_tool_info("write_file", args)
        # Path in body should be truncated to 60 chars (line will be longer due to "Path: " prefix)
        for line in body.split("\n"):
            if "Path:" in line:
                # Extract the path part after "Path: "
                path_part = line.split("Path: ", 1)[1] if "Path: " in line else ""
                assert len(path_part) <= 60

    def test_format_extracts_content(self):
        args = FakeArgs(content="hello world")
        title, body = format_tool_info("write_file", args)
        assert "Content: hello world" in body

    def test_format_truncates_long_content(self):
        args = FakeArgs(content="x" * 200)
        title, body = format_tool_info("write_file", args)
        # Content should be truncated with ...
        assert "..." in body
        # Body lines should not be excessively long
        for line in body.split("\n"):
            assert len(line) < 200

    def test_format_extracts_command(self):
        args = FakeArgs(command="echo hello")
        title, body = format_tool_info("bash", args)
        assert "Command: echo hello" in body

    def test_format_truncates_long_command(self):
        args = FakeArgs(command="echo " + "x" * 200)
        title, body = format_tool_info("bash", args)
        assert "..." in body or len(body.split("\n")[0]) < 200

    def test_format_extracts_file_path(self):
        args = FakeArgs(file_path="/tmp/bar.txt")
        title, body = format_tool_info("write_file", args)
        assert "File: /tmp/bar.txt" in body

    def test_format_unknown_tool_args_minimal(self):
        class Empty(BaseModel):
            pass
        title, body = format_tool_info("mystery_tool", Empty())
        assert title == "mystery_tool"
        assert "mystery_tool" in body

    def test_format_title_truncation(self):
        """Title should be truncated to 40 chars for M5Stack display."""
        args = FakeArgs(path="/tmp/test.py")
        long_tool_name = "x" * 50
        title, body = format_tool_info(long_tool_name, args)
        assert len(title) <= 40

    def test_format_multiple_fields(self):
        args = FakeArgs(path="/tmp/foo.py", content="test content", command="echo test")
        title, body = format_tool_info("write_file", args)
        assert "Path:" in body
        assert "Content:" in body
        # Should limit to 5 lines
        assert len(body.split("\n")) <= 5

    def test_format_empty_args(self):
        class Empty(BaseModel):
            def model_dump(self, **kwargs):
                return {}
        title, body = format_tool_info("tool", Empty())
        assert title == "tool"
        assert "Tool: tool" in body
