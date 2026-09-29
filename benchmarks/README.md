# Rendering benchmarks and layout review

[Architecture](../docs/architecture.md) · [Contributor guide](../CONTRIBUTING.md)

## Reviewing terminal layout quality

The [classic corpus](./fixtures/layout/) exercises chains, diamonds,
fan-out, fan-in with a continuation, bidirectional hubs, dependency shortcuts,
crossing connections, control links, feedback, groups, disconnected components,
and the storage architecture reference. The gallery also includes the supervisor
state machine with reciprocal transitions and long return labels. These are general graph shapes; node
names do not trigger layout rules.

### Review priorities

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

### Reproduce the review

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

The checked-in [measurements](./results/layout-quality.json) compare
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

### Current limits

Compound and cyclic ranking retain their existing policies. Local routing
refinement does not solve global crossing minimization or rearrange group frames.
Moving a control connection outside can increase rows or label references even
when it eliminates crossings. The fitter bounds width and prioritizes readable
text; it does not promise the minimum-area or crossing-free layout.

`tests/test_layout_quality.py` checks the corpus in all four directions, tests
ASCII and Unicode width fitting, and covers converging arrivals, clear perimeter
detours, and tiny-corner removal. Dedicated regression tests retain the compound,
cycle, Unicode-cell, fitting-budget, and serializer contracts.


## Rendering performance

The reconstruction adds work: label reservation and validation, preservation of
source models, and an optional eighth rendering attempt to improve graph labels.
Profiling the production fixtures identified repeated text measurement and
canvas serialization as useful optimization targets. The correctness checks,
model copies, and bounded quality search remain enabled.

### Measurements

#### Feature ownership and plugin refactor

[Architecture refactor evidence](results/architecture-refactor.json) compares the
saved pre-refactor working tree (including uncommitted work on `86a958b`) with the
new feature modules and registry. All nine fixture/width combinations produce
identical styled JSON in warm and fresh processes. Rich plain text and exact
style spans also match across 18 families and six themes.

Three-sample median timings are mixed, including cold-process regressions; this
refactor does not establish a speedup. Traced allocation peaks at width 100 are
slightly lower for the three production fixtures. These peaks measure Python
allocations during a warmed render, not total process memory. Use the commands
below with separate `--source-root` trees for repeatable timing comparisons.

#### Unified planning and routing update

The shared planning layer freezes the completed scene for reuse by plain text,
Rich, and styled JSON. This adds a cell snapshot allocation; graph routing also
does more work to keep branches, labels, and opposing lanes distinct. The
following warm measurements compare commit `88651629` with this update using
three measured runs after one warm-up, sequentially without concurrent tests.
Layouts intentionally differ, so these measure the complete behavior change.

| Fixture | Width | `88651629`, ms | Unified planning, ms |
|---|---:|---:|---:|
| Architecture | 68 | 64.2 | 88.0 |
| Architecture | 100 | 66.5 | 89.7 |
| Architecture | 160 | 76.8 | 96.0 |
| Supervisor state | 68 | 176.1 | 164.1 |
| Supervisor state | 100 | 164.3 | 162.6 |
| Supervisor state | 160 | 153.4 | 172.2 |
| Lease race sequence | 68 | 85.2 | 131.1 |
| Lease race sequence | 100 | 87.1 | 131.6 |
| Lease race sequence | 160 | 16.5 | 24.4 |

This is a layout-quality and shared-planning change, not a speed improvement.
Architecture and sequence fitting cost more in these samples; state timings
are mixed. Host variability remains significant. Raw timings, hashes, and
interpreter details are in [unified-layout.json](./results/unified-layout.json).

#### Earlier reconstruction measurements

Measured locally with the same Python interpreter, source fixtures, and editor
arguments. Baseline is commit `8960119`; “before” is the reconstructed renderer
before these optimizations; “optimized” includes them. Each warm result is the
median of seven measured runs after one warm-up. Each fresh-process result is
the median of five measured subprocesses after one discarded subprocess.

These are sequential samples on a shared machine, not universal performance
guarantees. Small differences, particularly startup-inclusive ones, can be
noise. Baseline and reconstruction intentionally produce different layouts;
this comparison measures their overall cost, not just the isolated cost of the
new data structures. Optimized output matches the before version byte for byte
in all nine measured cases, including both warm and fresh-process runs.

#### Warm process, milliseconds

This includes parsing, fitting, layout, validation, and styled JSON serialization,
but excludes launching Python.

| Fixture | Width | Checkpoint | Before | Optimized |
|---|---:|---:|---:|---:|
| Architecture | 68 | 43.1 | 76.8 | 38.5 |
| Architecture | 100 | 55.2 | 108.3 | 40.0 |
| Architecture | 160 | 74.9 | 114.8 | 44.4 |
| Supervisor state | 68 | 228.8 | 283.5 | 110.8 |
| Supervisor state | 100 | 171.8 | 368.6 | 121.1 |
| Supervisor state | 160 | 237.2 | 248.8 | 123.4 |
| Lease race sequence | 68 | 156.8 | 159.4 | 99.0 |
| Lease race sequence | 100 | 141.0 | 173.8 | 112.1 |
| Lease race sequence | 160 | 24.6 | 26.9 | 18.2 |

#### Fresh Python process, milliseconds, width 100

This includes process startup, as Neovim's `vim.system` invocation does.

| Fixture | Checkpoint | Before | Optimized |
|---|---:|---:|---:|
| Architecture | 287.0 | 254.4 | 231.4 |
| Supervisor state | 336.8 | 480.5 | 287.4 |
| Lease race sequence | 250.4 | 301.5 | 253.9 |

At the other widths, fresh-process reductions ranged from approximately 40% to
no detectable improvement; two small architecture cases were about 2% slower.
Startup and host variability can outweigh small rendering savings.

#### Traced allocation peaks, MiB, width 100

| Fixture | Checkpoint | Before | Optimized |
|---|---:|---:|---:|
| Architecture | 0.744 | 0.753 | 0.504 |
| Supervisor state | 0.643 | 0.647 | 0.408 |
| Lease race sequence | 1.653 | 1.730 | 1.131 |

Measured with `tracemalloc` around a separate warm invocation, outside timed
runs. These are Python allocation peaks during the call, not process RSS, and
exclude interpreter/import allocations and character-cache entries created
during warm-up. The optimized peaks are about 33–37% lower than before.

### Implemented optimizations

- **ASCII width fast path:** `str.isascii()` and `len()` avoid per-character
  classification for ordinary identifiers and labels.
- **Bounded character cache:** at most 1,024 Unicode width classifications.
  Whole diagram strings are not retained globally.
- **Immutable label measurements:** each `TextPlacement` measures its lines
  once and reuses those widths during reservation and validation. Replacing a
  placement creates fresh measurements.
- **Early bounds rejection:** impossible graph-label coordinates are rejected
  before allocating a placement object.
- **Row-by-row styled output:** serialization consumes `Canvas.iter_styled_rows()`
  instead of allocating a second matrix for the entire canvas. The existing
  `to_styled_pairs()` API still returns an independent complete snapshot.

The state example at width 100 still uses eight render attempts; architecture
and lease race use seven. The savings do not come from removing correctness
checks, changing output, or weakening fitting.

### Further options

1. **Parse once per fit operation.** Candidates currently reparse the source.
   A prepared immutable model could remove that repetition while maintaining
   independent candidate layouts. This requires coordinating the text, Rich,
   and styled adapters; measure it before changing their shared dispatch.
2. **Serialize only the selected candidate.** Fit scores could be computed from
   canvas metadata, with semantic chunks constructed only for the winner.
   This needs an internal canvas-result contract across diagram families.
3. **Persistent editor worker, if startup latency matters.** This could avoid
   repeated Python launches. It would add lifecycle, cancellation, and cache
   invalidation responsibilities to the Neovim integration, so it is a separate
   integration decision. Existing completed-render caching already helps when
   the source and width have not changed.

### Reproduce

Use the project's Python environment with dependencies installed:

```sh
python benchmarks/rendering.py --output /tmp/render-warm.json
python benchmarks/rendering.py --cold --repeats 5 --output /tmp/render-cold.json
```

`--source-root /path/to/checkout/src` selects an isolated source version while
using the same production fixtures. Do not run timing benchmarks concurrently
with tests or other benchmarks. Raw results, hashes, Python version, and timing
ranges are in [rendering.json](./results/rendering.json).
