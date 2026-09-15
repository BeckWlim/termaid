"""Tests for the Canvas character grid."""
from __future__ import annotations

from termaid.renderer.canvas import Canvas


def test_styled_rows_preserve_wide_cells_and_snapshot_independence():
    canvas = Canvas(5, 2)
    canvas.put_text(0, 0, '界x', style='edge_label')
    canvas.put_text(1, 1, '🗄', style='node')
    snapshot = canvas.to_styled_pairs()
    streamed_rows = list(canvas.iter_styled_rows())
    assert streamed_rows == snapshot
    assert streamed_rows[0][:3] == [('界', 'edge_label'), ('', 'edge_label'), ('x', 'edge_label')]
    snapshot[0][0] = ('!', 'arrow')
    assert canvas.get(0, 0) == '界'
    assert streamed_rows[0][0] == ('界', 'edge_label')


class TestWideCharBounds:
    def test_put_text_wide_char_below_canvas_does_not_crash(self):
        c = Canvas(10, 3)
        c.put_text(5, 0, "中")
        assert c.to_string() == ""

    def test_put_text_wide_char_negative_col_no_corruption(self):
        c = Canvas(10, 1)
        c.put_text(0, -5, "中文字")
        # Negative columns must not leak into the row via negative indexing
        assert all(c.get(0, i) == " " for i in range(10))

    def test_put_styled_text_wide_char_below_canvas_does_not_crash(self):
        c = Canvas(10, 3)
        c.put_styled_text(5, 0, [("中", "label")])
        assert c.to_string() == ""

    def test_put_text_wide_char_in_bounds_still_works(self):
        c = Canvas(10, 1)
        c.put_text(0, 0, "中x")
        assert c.get(0, 0) == "中"
        assert c.get(0, 1) == ""  # shadow cell
        assert c.get(0, 2) == "x"
