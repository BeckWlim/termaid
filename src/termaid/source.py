"""Classify the first Mermaid header using registry metadata, without imports."""
from __future__ import annotations

import re

from .core.contracts import DiagramType, ParsedSource
from .registry import DEFAULT_REGISTRY, DiagramRegistry


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---(?:\s*\n|$)", re.DOTALL)
_LEADING_ITEM_RE = re.compile(r"\s+|%%\{.*?\}%%|%%(?!\{)[^\n]*(?:\n|$)", re.DOTALL)
_HEADER_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?=$|[\s:;])")


def parse_source(source: str, *, registry: DiagramRegistry = DEFAULT_REGISTRY) -> ParsedSource:
    """Keep full text and body; unknown headers use the flowchart fallback."""
    text = _FRONTMATTER_RE.sub("", source.strip()).lstrip()
    header_offset = 0
    while leading_item := _LEADING_ITEM_RE.match(text, header_offset):
        header_offset = leading_item.end()
    body = text[header_offset:]
    header_match = _HEADER_RE.match(body)
    header = header_match.group() if header_match is not None else ""
    return ParsedSource(registry.identify(header), text, body)
