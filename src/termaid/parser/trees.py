"""Mermaid parsers for mindmaps, treemaps."""
from __future__ import annotations

import re

from ..model.trees import Mindmap, MindmapNode, Treemap, TreemapNode


# Mindmaps
# ------------------------------------------------------------------------
#
# Syntax (indentation-based):
#     mindmap
#       Root
#         Branch A
#           Leaf 1
#           Leaf 2
#         Branch B
#           Leaf 3

def parse_mindmap(text: str) -> Mindmap:
    """Parse a mermaid mindmap definition."""
    lines = text.strip().splitlines()
    mindmap = Mindmap()

    if not lines:
        return mindmap

    # Skip header line (mindmap)
    body_lines: list[tuple[int, str]] = []
    for line in lines[1:]:
        # Strip comments
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.rstrip()
        if not stripped.strip():
            continue

        # Measure indentation
        indent = len(stripped) - len(stripped.lstrip())
        label = stripped.strip()

        # Strip optional shape markers from Mermaid syntax:
        # (Round), [Square], {{Hexagon}}, )Cloud(, etc.
        for pattern, repl in [
            (r"^\((.+)\)$", r"\1"),        # (round)
            (r"^\[(.+)\]$", r"\1"),         # [square]
            (r"^\{\{(.+)\}\}$", r"\1"),     # {{hexagon}}
            (r"^\)(.+)\($", r"\1"),         # )cloud(
        ]:
            m = re.match(pattern, label)
            if m:
                label = m.group(1)
                break

        body_lines.append((indent, label))

    if not body_lines:
        return mindmap

    # Build tree from indentation
    stack: list[tuple[int, MindmapNode]] = []

    for indent, label in body_lines:
        node = MindmapNode(label=label)

        # Pop stack until we find a parent with less indentation
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        elif mindmap.root is None:
            mindmap.root = node
        else:
            # Multiple roots: attach to existing root
            mindmap.root.children.append(node)

        stack.append((indent, node))

    return mindmap


# Treemaps
# ------------------------------------------------------------------------
#
# Syntax:
#     treemap-beta
#     "Section 1"
#         "Leaf 1.1": 12
#         "Section 1.2"
#             "Leaf 1.2.1": 12
#     "Section 2"
#         "Leaf 2.1": 20

_NODE_RE = re.compile(r'^(\s*)"([^"]+)"(?:\s*:\s*([0-9]+(?:\.[0-9]*)?))?')


def parse_treemap(text: str) -> Treemap:
    """Parse a mermaid treemap definition."""
    lines = text.strip().splitlines()
    treemap = Treemap()

    if not lines:
        return treemap

    # Skip header line (treemap-beta)
    body_lines: list[tuple[int, str, float]] = []
    for line in lines[1:]:
        # Strip comments
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        m = _NODE_RE.match(line)
        if not m:
            continue

        indent = len(m.group(1))
        label = m.group(2)
        value = float(m.group(3)) if m.group(3) else 0
        body_lines.append((indent, label, value))

    if not body_lines:
        return treemap

    # Build tree from indentation
    # Stack: (indent_level, node)
    stack: list[tuple[int, TreemapNode]] = []

    for indent, label, value in body_lines:
        node = TreemapNode(label=label, value=value)

        # Pop stack until we find a parent with less indentation
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            treemap.roots.append(node)

        stack.append((indent, node))

    return treemap
