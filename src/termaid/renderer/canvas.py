"""Compatibility name for the shared terminal layout surface.

All diagram families plan on LayoutScene before an output adapter serializes
an immutable DiagramPlan. Existing low-level Canvas callers remain supported.
"""
from ..layout.scene import LayoutScene, DOWN, LEFT, RIGHT, UP

Canvas = LayoutScene

__all__ = ["Canvas", "DOWN", "LEFT", "RIGHT", "UP"]
