"""Tests for low-risk local desktop tools."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.tools.browser_open import BrowserOpenTool
from openjarvis.tools.list_files import ListFilesTool
from openjarvis.tools.system_time import SystemTimeTool


def test_system_time_is_read_only_and_returns_timezone():
    tool = SystemTimeTool()

    result = tool.execute()

    assert tool.spec.requires_confirmation is False
    assert result.success is True
    assert "UTC offset:" in result.content
    assert result.metadata["iso8601"]


def test_list_files_finds_matching_file_without_shell(tmp_path):
    wanted = tmp_path / "plan.md"
    wanted.write_text("# Plan", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    result = ListFilesTool().execute(path=str(tmp_path), pattern="*.md")

    assert result.success is True
    assert str(wanted.resolve()) in result.content
    assert "ignore.txt" not in result.content


def test_browser_open_defaults_to_start_page_without_confirmation():
    tool = BrowserOpenTool()
    with patch(
        "openjarvis.tools.browser_open.webbrowser.open", return_value=True
    ) as open_:
        result = tool.execute()

    assert tool.spec.requires_confirmation is False
    assert result.success is True
    open_.assert_called_once_with("https://www.bing.com/", new=2)


def test_browser_open_rejects_non_web_schemes():
    result = BrowserOpenTool().execute(url="file:///C:/Windows/win.ini")

    assert result.success is False
    assert "http://" in result.content
