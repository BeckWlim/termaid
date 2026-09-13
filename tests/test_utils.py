"""Tests for shared utility functions."""
from __future__ import annotations

from termaid.utils import display_width, truncate_to_width, wrap_display_text


class TestWrapDisplayText:
    def test_prefers_word_boundaries(self):
        assert wrap_display_text("alpha beta gamma", 10) == ["alpha", "beta gamma"]

    def test_hard_breaks_unspaced_text_by_display_cells(self):
        lines = wrap_display_text("abcdefgh", 4)
        assert lines == ["abcd", "efgh"]
        assert all(display_width(line) <= 4 for line in lines)

    def test_can_preserve_historical_long_tokens(self):
        token = "A" * 30
        assert wrap_display_text(token, 10, hard_break=False) == [token]

    def test_preserves_explicit_newlines(self):
        assert wrap_display_text("first\nsecond", 20) == ["first", "second"]


class TestTruncateToWidth:
    def test_fits_unchanged(self):
        assert truncate_to_width("hello", 10) == "hello"
        assert truncate_to_width("hello", 5) == "hello"

    def test_ascii_truncation(self):
        assert truncate_to_width("hello world", 6) == "hello."

    def test_cjk_never_exceeds_width(self):
        for width in range(1, 12):
            result = truncate_to_width("中文字符测试", width)
            assert display_width(result) <= width

    def test_cjk_truncation_keeps_whole_chars(self):
        # 3 columns: one wide char (2) + "." (1)
        assert truncate_to_width("中文字", 3) == "中."
        # 4 columns: can't fit half of the second wide char
        assert truncate_to_width("中文字", 4) == "中."

    def test_custom_ellipsis(self):
        assert truncate_to_width("hello world", 6, ellipsis="…") == "hello…"

    def test_tiny_width(self):
        assert display_width(truncate_to_width("中文", 1)) <= 1
        assert truncate_to_width("ab", 1) == "."
