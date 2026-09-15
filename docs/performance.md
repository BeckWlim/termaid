# Rendering performance

The reconstruction adds work: label reservation and validation, preservation of
source models, and an optional eighth rendering attempt to improve graph labels.
Profiling the production fixtures identified repeated text measurement and
canvas serialization as useful optimization targets. The correctness checks,
model copies, and bounded quality search remain enabled.

## Measurements

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

### Warm process, milliseconds

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

### Fresh Python process, milliseconds, width 100

This includes process startup, as Neovim's `vim.system` invocation does.

| Fixture | Checkpoint | Before | Optimized |
|---|---:|---:|---:|
| Architecture | 287.0 | 254.4 | 231.4 |
| Supervisor state | 336.8 | 480.5 | 287.4 |
| Lease race sequence | 250.4 | 301.5 | 253.9 |

At the other widths, fresh-process reductions ranged from approximately 40% to
no detectable improvement; two small architecture cases were about 2% slower.
Startup and host variability can outweigh small rendering savings.

### Traced allocation peaks, MiB, width 100

| Fixture | Checkpoint | Before | Optimized |
|---|---:|---:|---:|
| Architecture | 0.744 | 0.753 | 0.504 |
| Supervisor state | 0.643 | 0.647 | 0.408 |
| Lease race sequence | 1.653 | 1.730 | 1.131 |

Measured with `tracemalloc` around a separate warm invocation, outside timed
runs. These are Python allocation peaks during the call, not process RSS, and
exclude interpreter/import allocations and character-cache entries created
during warm-up. The optimized peaks are about 33–37% lower than before.

## Implemented optimizations

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

## Further options

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

## Reproduce

Use the project's Python environment with dependencies installed:

```sh
python benchmarks/rendering.py --output /tmp/render-warm.json
python benchmarks/rendering.py --cold --repeats 5 --output /tmp/render-cold.json
```

`--source-root /path/to/checkout/src` selects an isolated source version while
using the same production fixtures. Do not run timing benchmarks concurrently
with tests or other benchmarks. Raw results, hashes, Python version, and timing
ranges are in [rendering.json](../benchmarks/results/rendering.json).
