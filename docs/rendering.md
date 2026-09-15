# Rendering architecture

Termaid retains specialized layout algorithms for its 18 diagram types. Graph and
sequence renderers share a label planning contract; other renderers continue to
use their existing layouts and output adapters.

## Pipeline

1. Parse source into the existing diagram model.
2. Copy graph or sequence models at the renderer boundary, preserving original
   text and direction for repeated renders.
3. Measure nodes, participant columns, frames, routes, and label regions.
4. Reserve labels against geometry and previously reserved labels.
5. Validate the complete label batch, then paint it.
6. Serialize the canvas as text, Rich output, or version 1 styled JSON.

`layout.labels.TextPlacement` records an owner, row, column, measured lines, and
semantic style. Its coordinates use terminal display cells. `LabelPlan` reads a
geometry surface and reserves occupied cells without painting text. Rejected
placements write nothing. Before painting, the plan checks all labels again so
late geometry changes cannot leave a partially written batch.

Protected cells include node interiors, not just visible border characters.
Reserved text includes spaces and the second cell of wide characters. Explicit
inline graph labels retain their existing permission to occupy straight line
segments; ordinary labels cannot occupy connectors, arrowheads, or other text.

## Graph layouts

Flowchart, state, and architecture diagrams retain grid placement and orthogonal
routing. Route geometry, subgraph headings, and note boxes exist before edge
labels are planned. Label candidates use the requested width budget before
wrapping. Return labels prefer the outside margin. The same reservation surface
is used for all labels and reference markers.

If a label cannot fit, a numbered reference preserves its full text. References
remain ordered by source edge, and entries identify endpoints when a marker
cannot be placed unambiguously. Notes and scope headings keep their existing
diagram-specific drawing behavior; they are not reinterpreted as ordinary edge
labels.

## Sequence layouts

`SequenceLayout` records participant columns, box sizes, frame bounds, event
rows, and owned message-label placements. Original message text is retained
separately from provisional text used to measure horizontal spacing.

For a message spanning multiple participants, candidate label regions are the
gaps between consecutive lifelines along its arrow. The planner chooses the gap
requiring the fewest text rows, then the one closest to the sender. Self-message
labels use their own clear region, independently of the loop stroke. Loop reach
is capped at 15% of the measured canvas width, with a minimum allocation of ten cells
(eight visible cells plus the two-cell lifeline offset). The minimum takes priority
in narrow diagrams; short labels can use smaller loops within that range. Long labels can extend
beyond the loop while staying clear of the next lifeline. Final text height is measured before event rows
are assigned, so labels and horizontal arrows cannot share a row.

Geometry is painted before the shared label batch is validated and committed.
Intermediate arrow/lifeline crossings still use `x`. Message labels cannot mask
lifelines. Notes and scope headings retain their explicit overlay behavior.

## Bounded width fitting

The CLI compares visited candidates in this order:

1. Width overflow.
2. Height overflow when `--max-height` is supplied.
3. Number of label-reference entries.
4. Larger node-label budget.
5. Smaller output height and width.

Compact mode retains its three-render limit. Wrap/reflow fitting uses the
initial render and at most six label-budget candidates. One final render can
try more routing space if graph labels still require references, or vertical
reflow if the requested bounds remain unmet. Total renderer calls stay at most
eight. This is a bounded heuristic search, not a guarantee of the globally best
layout. A width budget is a maximum, not a requirement to stretch the drawing.

The Neovim CLI and styled JSON contracts are unchanged. Its 85% usable-width
budget, timeout, output limits, caching, and semantic highlights continue to work.

See [performance measurements](performance.md) for reconstruction costs, measured
optimizations, and a reproducible benchmark.

## Validation

The full test suite covers the existing diagram families and output adapters.
`tests/test_layout_plans.py` adds atomic rejection, label ownership, protected
geometry, CJK/emoji cells, repeated rendering, and the production lease-race
diagram at widths 68, 85, 100, 120, and 160 in both character sets. It checks
every participant lifeline on every message-label row, all arrowheads, and the
complete message text. `tests/test_fitting_policy.py` checks bounded retries and
selection of candidates with fewer references or within the height limit.

Run `python -m pytest tests/ -q` and `python -m compileall -q src tests`.
No static type checker or linter is configured in the repository. Changes to
layout boundaries also require an AST-assisted parameter-rebinding audit.
