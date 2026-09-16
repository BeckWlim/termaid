# Rendering architecture

All 18 diagram types enter through `layout.engine.plan`. Specialized strategies
retain their domain rules, including sequence lifelines, chart scales, and layered
graph placement. They resolve geometry on the shared `layout.scene.LayoutScene`,
then freeze terminal cells and semantic styles into an immutable `DiagramPlan`.
Output adapters only serialize that plan; they do not parse or rerun layout.
`renderer.canvas.Canvas` remains a compatibility alias for the shared surface.
The CLI also fits and validates `DiagramPlan` candidates directly. Text, Rich,
and styled JSON share the same candidate sequence, and only the selected plan
is serialized. Color and JSON chunk construction do not run for rejected fits.

The source keeps parsing, layout, and rendering as separate responsibilities.
Small diagram implementations are grouped into `charts`, `trees`, `boards`, and
`timelines` modules within `model/`, `parser/`, and `renderer/`. Subgraph bounds
and drawing-coordinate conversion live together in `layout/geometry.py`.
See the [source map](../CONTRIBUTING.md#architecture) for where to start reading.

## Pipeline

1. Parse source into the existing diagram model.
2. Copy graph or sequence models at the renderer boundary, preserving original
   text and direction for repeated renders.
3. Measure nodes, participant columns, frames, routes, and label regions.
4. Reserve labels against geometry and previously reserved labels.
5. Validate the complete label batch, then paint it.
6. Freeze geometry and custom style rules into `DiagramPlan`.
7. Serialize the same plan as text, Rich output, or version 1 styled JSON.

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

`layout.graph_plan.plan_graph` computes boxes, ports, and orthogonal routes before
placing their cells. BT and RL transform geometry before text is placed, keeping
labels readable and multiline text in its original order.

### Correctness and layout preferences

Hard constraints are complete graph content, orthogonal routes, intact node
interiors and group membership, visible edge direction, and labels that do not
overwrite geometry. `--strict-width` additionally requires the final output to
fit the requested terminal columns. An impossible route raises `RoutingError`;
an infeasible width is reported rather than silently clipped.

Rank, alignment, ports, shared trunks, label rows, and the number of visible
arrowheads are layout choices. Two arrivals may share one head at a common port
or use separate heads on different faces. Neither arrangement is mandatory.
One edge label per route must remain readable, inline or through a reference.
Identical declarations can share geometry without removing model edges.

### Terminal layout strategy

1. **Rank dependencies.** Ungrouped acyclic graphs retain every declared forward
   dependency and minimum edge length. A direct root-to-sink shortcut cannot
   pull the sink above its other predecessors. Bidirectional arrowheads do not
   add a reverse ranking dependency. Cyclic and compound graphs retain their
   bounded discovery-tree and group-separation policies.
2. **Order peers.** Barycenter ordering and bounded adjacent swaps reduce
   crossings while preserving group membership. Nodes on one rank share a row
   in TB/BT or a column in LR/RL.
3. **Align within the grid.** A solitary hub can align with the median existing
   peer column/row. This does not introduce an extra wide text column to achieve
   browser-style symmetry. Feedback and compound layouts keep their established
   corridors; `uniform_nodes` remains an explicit sizing choice.
4. **Reserve routing space.** Compatible solid fan-out edges, including
   bidirectional edges with matching endpoint types, may share a bus. Adjacent
   ungrouped siblings reserve a bus lane rather than one lane per destination.
   At least separate turn and approach cells remain available in compact output.
   Reciprocal nodes with a clear corridor can use facing ports without an outer
   return margin. Returns around intervening nodes keep their reserved lane.
5. **Choose routes.** All orientations consider preplanned sibling buses and
   congestion when comparing node faces. Opposing and unrelated collinear
   traffic cost more. Node borders, group headings, and foreign frames constrain
   routing. Return connections prefer outer corridors when available.
   A final pass for ungrouped rectangular nodes can shift a line to a clear
   parallel port to remove tiny consecutive corners. It can spend a small outer
   margin to eliminate multiple intersections; width fitting measures that
   margin too. A late turn is considered when another edge already approaches
   the same target along the flow axis, not as a rule for all long connections.
   Shared fan-out buses retain their early branching geometry.
   A nearby turn may shift a few cells to expose a labeled branch's approach,
   provided it adds no connector contacts, node overlap, or tiny segments.
6. **Place text.** Branch labels prefer exclusive sections of their routes.
   Available terminal cells determine wrapping; numbered references preserve
   text that cannot fit. References follow source-edge order and identify the
   endpoints when their marker is ambiguous. No label or reference may erase
   an arrowhead or an unconnected crossing.

`x` marks unconnected crossings. Shared prefixes/suffixes attached to a common
endpoint may form junctions, but sharing an endpoint does not make every later
intersection connected. Default triangle heads occupy straight border cells;
shape-specific markers may require a nearby fallback head. BT/RL transform
geometry before labels are placed, preserving readable text.

The staged approach draws on [Dagre](https://github.com/dagrejs/dagre/wiki) and
[ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html).
Termaid uses its own Python cell-grid implementation; neither engine is a runtime
dependency. Browser layouts guide topology and grouping, not pixel coordinates,
curves, unrestricted margins, or exact port counts. Fewer crossings may cost more
rows, so terminal width, labels, and total footprint must be reviewed together.

See [the layout review corpus](layout-quality.md) for classic samples, Mermaid
Live links, terminal-width measurements, and known limits of these heuristics.

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

Horizontal graph layouts use the budget during geometry planning as well as
label placement. Each node retains complete whitespace-delimited words, so the
trial label width cannot split identifiers such as `MasterService` or `NOF_SSD`.
Long edge sentences reserve their longest word's width rather than their entire
length in the first gap. Busy transitions reserve distinct routing columns;
group transitions keep those columns off frame borders. Incoming connections
also reserve separated ports before routes are chosen.

After measuring nodes and nested frames, one optional allocation pass spends
remaining width on complete short labels in their destination corridors. This
does not enlarge every gap. Vertical reciprocal transitions can use spare width
to separate opposing ports and fit labels between them, while retaining a margin
for outer return labels. This bounded allocation applies only with a width budget.
Routing considers already planned sibling buses,
keeps labeled approaches available, and compares congestion when selecting an
alternate face. A blocked label reservation is relaxed once rather than losing
the edge. All ordinary node obstacles and directional costs remain active.

A label may extend beyond a short exclusive branch when its rectangle and its
approach to that branch are clear. It cannot cross another connector, overwrite
a border, or exceed the width budget. A single exclusive straight cell can anchor
a label; context cells must not let it borrow a shared trunk. This applies to
vertical and horizontal segments. Numbered references remain the fallback.
In `wrap` mode, an infeasible horizontal layout reports width overflow instead
of forcing identifiers into arbitrary fragments; `--strict-width` rejects it.
The optional vertical `reflow` attempt uses the available text width instead of
a fixed five-character limit. For ungrouped graphs with ordinary node sizing,
measured columns are narrowed before routing when they exceed that width.
Labels wrap from their source text while routing gaps and endpoint-port space
remain reserved. Compound, explicitly positioned, and uniform-node layouts keep
their existing sizing policies.

Performance and historical width-allocation measurements live in
[performance.md](performance.md) and [benchmarks/results](../benchmarks/results/).
Consumer configuration belongs in [integrations.md](integrations.md).

## Validation

The classic corpus checks all four flow directions, ASCII/Unicode, topology,
route clearance, complete text, and 80/120/160-column fitting. Regression tests
cover compound frames, feedback, labels, CJK/emoji cells, serializer parity, and
bounded fitting retries. Snapshots document reviewed output, but exact arrowhead
counts, arrival faces, and footnote identities are not correctness contracts.

Run `python -m pytest tests/ -q` and `python -m compileall -q src tests`.
No static type checker or linter is configured in the repository. Changes to
layout boundaries also require an AST-assisted parameter-rebinding audit.
