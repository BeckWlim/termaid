"""Shared utility functions for termaid."""
from __future__ import annotations

import unicodedata


def _is_wide(ch: str) -> bool:
    """Return True if *ch* occupies 2 terminal columns."""
    if unicodedata.east_asian_width(ch) in ("F", "W"):
        return True
    # Emoji and symbols that render wide despite east_asian_width=N
    cp = ord(ch)
    if (
        0x2600 <= cp <= 0x27BF      # Misc Symbols, Dingbats
        or 0x1F300 <= cp <= 0x1FAFF  # Emoji blocks (Misc Symbols & Pictographs through Symbols Extended-A)
        or 0xFE00 <= cp <= 0xFE0F   # Variation selectors
    ):
        return True
    return False


def display_width(text: str) -> int:
    """Return the terminal display width of *text*.

    East-Asian wide / fullwidth characters and emoji occupy 2 terminal
    columns; everything else occupies 1.
    Uses only the stdlib ``unicodedata`` module.
    """
    w = 0
    for ch in text:
        w += 2 if _is_wide(ch) else 1
    return w


def wrap_display_text(
    text: str,
    max_width: int,
    *,
    hard_break: bool = True,
) -> list[str]:
    """Wrap text to terminal display cells, hard-breaking long tokens.

    Whitespace is preferred as a break point, but unlike ``textwrap`` this
    also handles CJK text and identifiers that contain no spaces. Explicit
    newlines are preserved.
    """
    if max_width < 1:
        raise ValueError("max_width must be positive")

    wrapped: list[str] = []
    for logical_line in text.split("\n"):
        if not hard_break:
            words = logical_line.split()
            if not words:
                wrapped.append(logical_line)
                continue
            current = words[0]
            for word in words[1:]:
                if display_width(current) + 1 + display_width(word) <= max_width:
                    current += " " + word
                else:
                    wrapped.append(current)
                    current = word
            wrapped.append(current)
            continue

        remaining = logical_line
        if remaining == "":
            wrapped.append("")
            continue

        while display_width(remaining) > max_width:
            used = 0
            end = 0
            last_space = -1
            for index, ch in enumerate(remaining):
                char_width = 2 if _is_wide(ch) else 1
                if used + char_width > max_width:
                    break
                used += char_width
                end = index + 1
                if ch.isspace():
                    last_space = end

            # A width of one cannot contain a wide glyph. Keep the glyph
            # intact and let the caller decide that the constraint is
            # unsatisfiable rather than looping forever or corrupting UTF-8.
            if end == 0:
                end = 1

            split_at = last_space if last_space > 0 else end
            line = remaining[:split_at].rstrip()
            if not line:
                line = remaining[:end]
                split_at = end
            wrapped.append(line)
            remaining = remaining[split_at:].lstrip()

        wrapped.append(remaining.rstrip())

    return wrapped


def truncate_to_width(text: str, width: int, ellipsis: str = ".") -> str:
    """Truncate *text* so its display width fits in *width* columns.

    Appends *ellipsis* when truncation happens. Never splits a wide
    character: the result's display width is always <= width.
    """
    if display_width(text) <= width:
        return text

    def clip(s: str, cols: int) -> str:
        out: list[str] = []
        w = 0
        for ch in s:
            cw = 2 if _is_wide(ch) else 1
            if w + cw > cols:
                break
            out.append(ch)
            w += cw
        return "".join(out)

    ell_w = display_width(ellipsis)
    if width <= ell_w:
        return clip(ellipsis, width)
    return clip(text, width - ell_w) + ellipsis
