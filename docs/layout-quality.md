# Reviewing terminal layout quality

The [classic corpus](../benchmarks/fixtures/layout/) exercises chains, diamonds,
fan-out, fan-in with a continuation, bidirectional hubs, dependency shortcuts,
crossing connections, control links, feedback, groups, disconnected components,
and the storage architecture reference. The gallery also includes the supervisor
state machine with reciprocal transitions and long return labels. These are general graph shapes; node
names do not trigger layout rules.

## Review priorities

1. Preserve nodes, edges, directions, complete text, and group membership.
2. Fit the requested terminal columns without overwriting boxes or labels.
3. Make the hierarchy and individual connections easy to follow. A shortcut
   should not pull a downstream node above another predecessor.
4. Reduce unrelated intersections and ambiguous shared segments. A modest
   perimeter detour is worthwhile when it removes several intersections.
5. Avoid tiny consecutive corners when a clear parallel lane or another valid
   port gives a straighter route. Keep intentional shared buses intact.
6. Prefer compact, balanced geometry within the existing column grid. For
   converging connections, consider a late turn when another arrival already
   follows the flow axis. Long edges alone do not justify a late turn.
7. Use available width for competing label corridors, and allow labels beside
   short exclusive segments before falling back to references. Small turn shifts
   can expose a label's approach without adding crossings or tiny corners.
8. Review label references and total rows alongside crossings. A browser's
   generous whitespace, curves, or exact symmetry are not terminal targets.

Arrowhead counts, shared versus separate destination ports, fixed arrival
faces, and specific footnote identities are preferences rather than universal
contracts. Tests should check meaning, geometry, and text preservation.

## Reproduce the review

From the repository root:

```sh
PYTHONPATH=src .venv/bin/python benchmarks/layout_quality.py --output-dir /tmp/termaid-layout-review
```

Open `/tmp/termaid-layout-review/index.html`. Its width selector compares
80/120/160-column output; each sample includes its source and Mermaid Live links
with Dagre and ELK selected explicitly. `metrics.json` records actual width,
height, unconnected crossing markers, references, and render failures. Individual
text files allow terminal inspection. Supply `--baseline-dir` with an earlier
review directory to display its output alongside the current rendering.

The checked-in [measurements](../benchmarks/results/layout-quality.json) compare
against the working tree captured immediately before this optimization, including
its existing uncommitted changes. They are not a comparison against Git HEAD.
The newly added state sample has no recorded baseline and uses `null` for it.

For an optional engine-level reference, generate `graphs.json` with the command
above and run:

```sh
node benchmarks/layout_reference.cjs /path/to/dagre.min.js /path/to/elk.bundled.js /tmp/termaid-layout-review/graphs.json /tmp/termaid-layout-review/references.json
```

The recorded reference uses Dagre 1.1.5 and ELK.js 0.10.0 with uniform abstract
120 × 50 boxes. It checks hierarchy and alignment, not pixel-perfect Mermaid
output. Compound examples are excluded from that flattened comparison. ELK uses
unit edge lengths there; Dagre also receives each declared minimum edge length.
Neither tool is a Termaid runtime dependency. The relevant engine documentation
is [Dagre's layout guide](https://github.com/dagrejs/dagre/wiki) and
[ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html).

## Current limits

Compound and cyclic ranking retain their existing policies. Local routing
refinement does not solve global crossing minimization or rearrange group frames.
Moving a control connection outside can increase rows or label references even
when it eliminates crossings. The fitter bounds width and prioritizes readable
text; it does not promise the minimum-area or crossing-free layout.

`tests/test_layout_quality.py` checks the corpus in all four directions, tests
ASCII and Unicode width fitting, and covers converging arrivals, clear perimeter
detours, and tiny-corner removal. Dedicated regression tests retain the compound,
cycle, Unicode-cell, fitting-budget, and serializer contracts.
