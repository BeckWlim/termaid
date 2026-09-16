"""Data models for user journeys, kanban boards."""
from __future__ import annotations

from dataclasses import dataclass, field


# User journeys
# ------------------------------------------------------------------------

@dataclass
class JourneyTask:
    title: str
    score: int = 3       # 1-5 satisfaction
    actors: list[str] = field(default_factory=list)


@dataclass
class JourneySection:
    title: str
    tasks: list[JourneyTask] = field(default_factory=list)


@dataclass
class Journey:
    title: str = ""
    sections: list[JourneySection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Kanban boards
# ------------------------------------------------------------------------

@dataclass
class KanbanCard:
    title: str
    metadata: str = ""  # optional tag/assignee


@dataclass
class KanbanColumn:
    title: str
    cards: list[KanbanCard] = field(default_factory=list)


@dataclass
class Kanban:
    title: str = ""
    columns: list[KanbanColumn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
