"""Mermaid parsers for user journeys, kanban boards."""
from __future__ import annotations

import re

from ..model.boards import Journey, JourneySection, JourneyTask, Kanban, KanbanColumn, KanbanCard


# User journeys
# ------------------------------------------------------------------------
#
# Syntax:
#     journey
#         title My working day
#         section Go to work
#             Make tea: 5: Me
#             Go upstairs: 3: Me
#             Do work: 1: Me, Cat
#         section Go home
#             Go downstairs: 5: Me
#             Sit down: 5: Me

def parse_journey(text: str) -> Journey:
    """Parse a mermaid user journey definition."""
    lines = text.strip().splitlines()
    journey = Journey()

    if not lines:
        return journey

    current_section: JourneySection | None = None

    for line in lines[1:]:  # skip "journey" header
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        if lower.startswith("title "):
            journey.title = stripped[6:].strip()
            continue

        if lower.startswith("section "):
            current_section = JourneySection(title=stripped[8:].strip())
            journey.sections.append(current_section)
            continue

        # Task: "Task name: score: actor1, actor2"
        if ":" in stripped:
            parts = stripped.split(":")
            title = parts[0].strip()
            score = 3
            actors: list[str] = []

            if len(parts) >= 2:
                try:
                    score = int(parts[1].strip())
                    score = max(1, min(5, score))
                except ValueError:
                    pass

            if len(parts) >= 3:
                actors = [a.strip() for a in parts[2].split(",") if a.strip()]

            if current_section is None:
                current_section = JourneySection(title="")
                journey.sections.append(current_section)

            current_section.tasks.append(JourneyTask(
                title=title, score=score, actors=actors,
            ))

    return journey


# Kanban boards
# ------------------------------------------------------------------------
#
# Syntax:
#     kanban
#         Todo
#             Design homepage
#             Fix login bug
#         In Progress
#             API integration
#         Done
#             Database setup

def _clean_title(text: str) -> str:
    """Extract the display title, handling the id[Title] form."""
    m = re.match(r'^[\w-]*\[(.+)\]$', text)
    title = m.group(1) if m else text
    return title.strip().strip("\"'")


def parse_kanban(text: str) -> Kanban:
    """Parse a mermaid kanban definition."""
    lines = text.strip().splitlines()
    kb = Kanban()

    if not lines:
        return kb

    # Detect indentation levels: columns are at one level, cards at a deeper level
    body_lines: list[tuple[int, str]] = []
    for line in lines[1:]:  # skip "kanban" header
        comment_idx = line.find("%%")
        if comment_idx >= 0:
            line = line[:comment_idx]

        stripped = line.rstrip()
        if not stripped.strip():
            continue

        indent = len(stripped) - len(stripped.lstrip())
        body_lines.append((indent, stripped.strip()))

    if not body_lines:
        return kb

    # Find column indent level (the minimum indent)
    min_indent = min(indent for indent, _ in body_lines)

    current_column: KanbanColumn | None = None

    for indent, item_text in body_lines:
        if indent <= min_indent:
            # Column header
            current_column = KanbanColumn(title=_clean_title(item_text))
            kb.columns.append(current_column)
        else:
            # Card
            if current_column is None:
                current_column = KanbanColumn(title="")
                kb.columns.append(current_column)

            # Extract metadata ("card title @tag") before unwrapping id[Title]
            metadata = ""
            card_title = item_text
            if "@" in item_text:
                parts = item_text.rsplit("@", 1)
                card_title = parts[0].strip()
                metadata = "@" + parts[1].strip()

            current_column.cards.append(
                KanbanCard(title=_clean_title(card_title), metadata=metadata)
            )

    return kb
