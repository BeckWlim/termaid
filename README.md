<h1 align="center">termaid</h1>

<p align="center">Render Mermaid diagrams in your terminal or Python app.</p>

<p align="center">
  <img src="termaid-demo.gif" alt="termaid demo" width="800">
</p>

**[Try it online at termaid.com](https://termaid.com)**

## Features

- **18 diagram types:** flowcharts, sequence, class, ER, state, block, git, gantt, architecture, pie, treemap, mindmap, timeline, kanban, quadrant, XY chart, user journey, and packet
- **Zero dependencies:** pure Python, nothing to install beyond the package itself
- **Terminal-aware:** auto-fits diagrams to terminal width with progressive compaction
- **Best-effort crossing avoidance:** shared fan-out branches and outer return lanes; `╳` (`x` in ASCII) distinguishes unconnected crossings from junctions
- **Rich and Textual integration:** colored output and TUI widgets with optional extras
- **6 color themes:** default, terra, neon, mono, amber, phosphor
- **ASCII fallback:** works on any terminal, even the most basic ones
- **Pipe-friendly CLI:** `cat diagram.mmd | termaid` just works

## Why?

Mermaid is great for documentation, but rendering it usually means spinning up a browser or calling an external service. termaid lets you render diagrams over SSH, in CI logs, inside TUI apps, or anywhere you have a Python environment. It was built because the existing tools in this space, like [mermaid-ascii](https://github.com/AlexanderGrooff/mermaid-ascii) (Go) and [beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) (TypeScript), don't offer a native Python library you can import and call directly.

## Install

```bash
pip install termaid
```

Or try it without installing:

```bash
uvx termaid diagram.mmd
```

## Quick start

### CLI

```bash
termaid diagram.mmd
echo "graph LR; A-->B-->C" | termaid
termaid diagram.mmd --theme neon
termaid diagram.mmd --ascii
termaid diagram.mmd --format styled-json
```

### Python

```python
from termaid import render

print(render("graph LR\n  A --> B --> C"))
```

```python
# Colored output (requires: pip install termaid[rich])
from termaid import render_rich
from rich import print as rprint

rprint(render_rich("graph LR\n  A --> B", theme="terra"))
```

```python
# Textual TUI widget (requires: pip install termaid[textual])
from termaid import MermaidWidget

widget = MermaidWidget("graph LR\n  A --> B")
```

## Supported diagram types

### Flowcharts

All directions supported: `LR`, `RL`, `TD`/`TB`, `BT`.

```mermaid
graph TD
    A[Start] --> B{Is valid?}
    B -->|Yes| C(Process)
    C --> D([Done])
    B -->|No| E[Error]
```

```
┌─────────────┐
│             │
│    Start    │
│             │
└──────┬──────┘
       │
       │
       ▼
┌──────◇──────┐
│             │
│  Is valid?  │
│             │
└──────◇──────┘
       │
       │
       ╰──────────────────╮
    Yes│                  │No
       ▼                  ▼
╭─────────────╮    ┌─────────────┐
│             │    │             │
│   Process   │    │    Error    │
│             │    │             │
╰──────┬──────╯    └─────────────┘
       │
       │
       ▼
╭─────────────╮
(             )
(    Done     )
(             )
╰─────────────╯
```

**Node shapes:** rectangle `[text]`, rounded `(text)`, diamond `{text}`, stadium `([text])`, subroutine `[[text]]`, circle `((text))`, double circle `(((text)))`, hexagon `{{text}}`, cylinder `[(text)]`, asymmetric `>text]`, parallelogram `[/text/]`, trapezoid `[/text\]`, and `@{shape}` syntax

**Edge styles:** solid `-->`, dotted `-.->`, thick `==>`, bidirectional `<-->`, circle endpoint `--o`, cross endpoint `--x`, labeled `-->|text|`, variable length `--->`, `---->`

**Styling:** `classDef`, `style`, `linkStyle` directives, `:::className` suffix

**Subgraphs:** nesting, cross-boundary edges, per-subgraph `direction` override

**Other:** `%%` comments, `;` line separators, Markdown labels `` "`**bold** *italic*`" ``, `&` operator (`A & B --> C`)

### Sequence diagrams

```mermaid
sequenceDiagram
    Alice->>Bob: Hello Bob
    Bob-->>Alice: Hi Alice
    Alice->>Bob: How are you?
    Bob-->>Alice: Great!
```

```
 ┌──────────┐      ┌──────────┐
 │  Alice   │      │   Bob    │
 └──────────┘      └──────────┘
       ┆ Hello Bob       ┆
       ──────────────────►
       ┆ Hi Alice        ┆
       ◄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
       ┆ How are you?    ┆
       ──────────────────►
       ┆ Great!          ┆
       ◄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
       ┆                 ┆
```

**Message types:** solid arrow `->>`, dashed arrow `-->>`, solid line `->`, dashed line `-->`

**Participants:** `participant`, `actor`, aliases

### Class diagrams

```mermaid
classDiagram
    class Animal {
        +String name
        +int age
        +makeSound()
    }
    class Dog {
        +String breed
        +fetch()
    }
    Animal <|-- Dog
```

```
  ┌──────────────┐
  │    Animal    │
  ├──────────────┤
  │ +String name │
  │ +int age     │
  ├──────────────┤
  │ +makeSound() │
  └──────────────┘
          △
          │
          │
          │
  ┌───────────────┐
  │      Dog      │
  ├───────────────┤
  │ +String breed │
  ├───────────────┤
  │ +fetch()      │
  └───────────────┘
```

**Relationships:** inheritance `<|--`, composition `*--`, aggregation `o--`, association `--`, dependency `..>`, realization `..|>`

**Members:** attributes and methods with visibility (`+` public, `-` private, `#` protected, `~` package)

### ER diagrams

```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
```

```
  ┌──────────────┐
  │   CUSTOMER   │
  └──────────────┘
          │1
          │ places
          │
          │0..*
  ┌──────────────┐
  │    ORDER     │
  └──────────────┘
          │1
          │ contains
          │
          │1..*
  ┌──────────────┐
  │  LINE-ITEM   │
  └──────────────┘
```

**Cardinality:** `||` (exactly one), `o|` (zero or one), `}|` (one or more), `o{` (zero or more)

**Line styles:** solid `--`, dashed `..`

**Attributes:** type, name, keys (`PK`, `FK`, `UK`), comments

### State diagrams

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Processing : start
    Processing --> Done : complete
    Done --> [*]
```

```
╭───────◯──────╮
│              │
│      ●       │
│              │
╰───────◯──────╯
        │
        │
        ▼
╭──────────────╮
│              │
│     Idle     │
│              │
╰───────┬──────╯
        │
   start│
        ▼
╭──────────────╮
│              │
│  Processing  │
│              │
╰───────┬──────╯
        │
complete│
        ▼
╭──────────────╮
│              │
│     Done     │
│              │
╰───────┬──────╯
        │
        │
        ▼
╭───────◯──────╮
│              │
│      ◉       │
│              │
╰───────◯──────╯
```

**Features:** `[*]` start/end states, transition labels, `state "name" as alias`, composite states (`state Parent { }`), stereotypes (`<<choice>>`, `<<fork>>`, `<<join>>`)

### Block diagrams

```mermaid
block-beta
    columns 3
    A["Frontend"] B["API"] C["Database"]
```

```
  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │          │    │          │    │          │
  │ Frontend │    │   API    │    │ Database │
  │          │    │          │    │          │
  └──────────┘    └──────────┘    └──────────┘
```

**Features:** `columns N`, column spanning (`blockname:N`), links between blocks, nested blocks

### Git graphs

```mermaid
gitGraph
   commit id: "init"
   commit id: "feat"
   branch develop
   commit id: "dev-1"
   commit id: "dev-2"
   checkout main
   commit id: "fix"
   merge develop id: "merge"
```

```
  main    ───●─────●──────┼──────────────●──────●─
           init  feat     │             fix   merge
                          │                     │
  develop                 ●───────●─────────────┼
                        dev-1   dev-2
```

**Directions:** `LR` (default), `TB`, `BT`

**Commands:** `commit` (with `id:`, `type:`, `tag:`), `branch` (with `order:`), `checkout`/`switch`, `merge`, `cherry-pick`

**Commit types:** `NORMAL` (●), `REVERSE` (✖), `HIGHLIGHT` (■)

**Config:** `%%{init: {"gitGraph": {"mainBranchName": "master"}}}%%`

### Pie charts

Yes, the syntax says `pie`. No, we don't draw a circle. I know. Have you ever tried to read a pie chart made of `█` and `▓`? Exactly. We render them as horizontal bar charts instead.

```mermaid
pie title Pets adopted by volunteers
    "Dogs" : 386
    "Cats" : 85
    "Rats" : 15
```

```
  Dogs┃████████████████████████████████  79.4%
  Cats┃▓▓▓▓▓▓▓  17.5%
  Rats┃░   3.1%
```

**Features:** `title`, `showData` (display raw values), `%%` comments

### Treemaps

```mermaid
treemap-beta
    "Frontend"
        "React": 40
        "CSS": 15
    "Backend"
        "API": 35
        "Auth": 10
```

```
┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
┆             Frontend              ┆ ┆          Backend           ┆
┆┌───────────────────────┐ ┌───────┐┆ ┆┌───────────────────┐ ┌────┐┆
┆│         React         │ │  CSS  │┆ ┆│        API        │ │Auth│┆
┆│          40           │ │  15   │┆ ┆│        35         │ │ 10 │┆
┆│                       │ │       │┆ ┆│                   │ │    │┆
┆└───────────────────────┘ └───────┘┆ ┆└───────────────────┘ └────┘┆
└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
```

**Features:** nested sections via indentation, `"label": value` syntax, proportional sizing, `%%` comments

### Mindmaps

```mermaid
mindmap
  Project
    Design
      Wireframes
      Mockups
    Development
      Frontend
      Backend
    Testing
```

```
          ╭─ Design ──╭─ Wireframes
          │           ╰─ Mockups
Project ──├─ Development ──╭─ Frontend
          │                ╰─ Backend
          ╰─ Testing
```

**Features:** indentation-based nesting, automatic overflow to the left when many children, rounded/sharp/ASCII branch characters, Mermaid shape markers stripped (`(round)`, `[square]`, `{{hexagon}}`, `)cloud(`)

### XY Charts

```mermaid
xychart-beta
    title "Monthly Revenue"
    x-axis [Jan, Feb, Mar, Apr, May, Jun]
    bar [12, 18, 25, 20, 30, 35]
```

```
                 Monthly Revenue

     35 │                              ████
        │                              ████
        │                        ▄▄▄▄  ████
     28 │                        ████  ████
        │            ▄▄▄▄        ████  ████
        │            ████        ████  ████
     21 │            ████  ▄▄▄▄  ████  ████
        │      ▄▄▄▄  ████  ████  ████  ████
        │      ████  ████  ████  ████  ████
     14 │      ████  ████  ████  ████  ████
        │████  ████  ████  ████  ████  ████
        │████  ████  ████  ████  ████  ████
      7 │████  ████  ████  ████  ████  ████
        │████  ████  ████  ████  ████  ████
        │████  ████  ████  ████  ████  ████
      0 └──┬─────┬─────┬─────┬─────┬─────┬─
          Jan   Feb   Mar   Apr   May   Jun
```

**Features:** bar charts, line charts, bar+line combos, horizontal orientation (`xychart horizontal`), axis labels, `xychart` and `xychart-beta` keywords, rounded/sharp line corners, JSON ingest

### User Journeys

```mermaid
journey
    title My working day
    section Go to work
        Make tea: 5: Me
        Go upstairs: 3: Me
        Do work: 1: Me, Cat
    section Go home
        Go downstairs: 5: Me
        Sit down: 5: Me
```

```
  My working day

  ● Cat
  ◆ Me

  ╭───────────── Go to work ──────────────╮   ╭───────── Go home ───────────╮

  ╭◆─────────╮ ╭◆────────────╮ ╭●◆───────╮    ╭◆──────────────╮ ╭◆─────────╮
 ─│ Make tea │─│ Go upstairs │─│ Do work │────│ Go downstairs │─│ Sit down │────►
  ╰──────────╯ ╰─────────────╯ ╰─────────╯    ╰───────────────╯ ╰──────────╯
       😄            😐            😞                😄              😄
```

**Features:** sections, satisfaction scores (😞-😄), multi-actor support with distinct symbols (●◆■▲), rounded/sharp/ASCII corners

### Packet Diagrams

```mermaid
packet
    0-15: "Source Port"
    16-31: "Destination Port"
    32-63: "Sequence Number"
    64-95: "Acknowledgment Number"
```

```
 0                                             15 16                                           31
 ╭───────────────────────────────────────────────┬───────────────────────────────────────────────╮
 │                 Source Port                   │               Destination Port                │
 ╰───────────────────────────────────────────────┴───────────────────────────────────────────────╯
 32                                                                                            63
 ╭───────────────────────────────────────────────────────────────────────────────────────────────╮
 │                                       Sequence Number                                         │
 ╰───────────────────────────────────────────────────────────────────────────────────────────────╯
 64                                                                                            95
 ╭───────────────────────────────────────────────────────────────────────────────────────────────╮
 │                                    Acknowledgment Number                                      │
 ╰───────────────────────────────────────────────────────────────────────────────────────────────╯
```

**Features:** bit-aligned field layouts, boundary numbers, auto-increment (`+N`) syntax, separated boxes per row, truncated label legend with bit ranges, `packet` and `packet-beta` keywords

## CLI options

Sequence participant boxes share the header row height; width matching is capped to avoid
stretching every box around one long name. During width fitting, scope headings wrap to
their frame's content width independently of participant labels. Styled output marks scope
borders as `subgraph` and scope hints as `subgraph_label` so editors can keep ranges muted.
Disjoint flowchart edge labels can align on one row while retaining separation.
During width fitting, node boxes and connection layout take priority over transition sentences.
Return corridors have a bounded structural width; long labels do not set their width. The fitter
compares width and height limits, reference count, node-label budget, and output height.
When references remain, it tries one layout with more routing space. Labels use the existing `--width` budget and
wrap whole words into clear rectangles beside their paths, preferring balanced lines.
With `--width`, labels use the available width before wrapping, extending beyond the node
layout when needed. Without a width budget, they prefer existing diagram space. Return labels
prefer the outer margin. They never overwrite connectors or nodes. A label that still cannot fit uses a
numbered reference such as `[1]`, with its full text below the diagram. References follow source
edge order. If a reference needs a nearby position or cannot fit safely, its entry also names
the source and target. The reference list wraps within the same width budget.
`--arrow-position middle` places directional flowchart arrowheads on clear straight segments,
preferring unshared portions near the middle. This helps distinguish converging edges.
Placement is best effort: short routes can retain endpoint heads; circle and cross endpoints
always stay at their endpoints. The default remains `--arrow-position end`.
These options preserve terminal text size and apply to the graph renderer, not sequence arrows.
Sequence arrows leave a blank cell beside endpoint lifelines; self-loops reserve room before
the next participant. Self-loop reach is capped at 15% of the measured diagram width, with
at least eight visible cells in each horizontal leg (plus lifeline clearance).
This minimum takes priority in narrow diagrams. Labels can extend beyond the loop within their reserved
clear region; longer text does not force the loop past its cap.
Unrelated arrow crossings and unavoidable crossings through other lifelines use a small `x`
in both Unicode and ASCII output.
Scope headings cover only their own text area, preserving the other vertical lines on the row.
Message labels use a measured gap between participant lifelines, independently of the
participant-box wrapping limit. An arrow spanning several participants can cross intermediate
lifelines; its label wraps in one clear gap without erasing them. Label height is reserved before
arrow rows are assigned. Punctuation boundaries help keep short endings with their preceding phrase.

Graph and sequence labels are planned and checked before painting. Rendering these diagrams
keeps the caller's original model unchanged, including across repeated renders at different widths.
See [rendering architecture](docs/rendering.md) for layout contracts and validation.

Width-fitted labels prefer whole words, then punctuation, identifier separators, and
camel-case boundaries. For example, `metadata_shard[s].mutex` wraps before `.mutex`
when the complete name cannot fit. An unbreakable segment wider than the budget still
splits by display cells; explicit newlines and complete CJK characters are preserved.
The shared `termaid.utils.wrap_display_text(text, max_width)` utility supplies this policy
for flowchart nodes and sequence participants, messages, notes, and scope headings.

```python
from termaid.utils import wrap_display_text

wrap_display_text("metadata_shard[s].mutex", 20)
# ["metadata_shard[s]", ".mutex"]
wrap_display_text("Read complete words here", 14)
# ["Read complete", "words here"]
```


| Flag | Description |
|------|-------------|
| `--ascii` | ASCII-only output (no Unicode box-drawing) |
| `--theme NAME` | Color theme (requires `pip install termaid[rich]`). Use `--themes` to list |
| `--themes` | List all available color themes |
| `--demo [TYPE]` | Render sample diagrams (`all`, `flowchart`, `sequence`, `mindmap`, etc.) |
| `--padding-x N` | Horizontal padding inside boxes (default: 4) |
| `--padding-y N` | Vertical padding inside boxes (default: 2) |
| `--gap N` | Space between nodes (default: 4). Use `1` or `2` for compact diagrams |
| `--arrow-position {end,middle}` | Flowchart arrowhead placement; default `end`, best-effort `middle` |
| `--inline-edge-labels` | Attach flowchart labels directly to their edges |
| `--width N` | Target output width in terminal display cells; fit oversized diagrams with smaller spacing and wrapped labels |
| `--strict-width` | Fail without oversized output if the requested width cannot be met |
| `--fit-mode compact\|wrap\|reflow` | Fit spacing only, wrap labels, or also allow vertical flowchart reflow |
| `--uniform-nodes` | Give flowchart nodes common width and height before fitting and routing; junctions remain minimal |
| `--no-auto-fit` | Disable automatic compaction when diagram exceeds terminal width |
| `--sharp-edges` | Sharp corners on edge turns instead of rounded |
| `-o FILE` | Write output to file instead of stdout |
| `--format styled-json` | Emit versioned semantic text chunks for editor and UI integrations |
| `--show-ids` | Show node IDs alongside labels for debugging (e.g. `myId: My Label`) |
| `--json TYPE` | Pipe JSON/tabular data and render as `treemap`, `pie`, `mindmap`, `flowchart`, or `xychart` |
| `--tui` | Interactive TUI viewer (requires `pip install termaid[tui]`) |

## Python API

### `render(source, ...) -> str`

Render a Mermaid diagram as a plain text string. Auto-detects diagram type.
`arrow_position="middle"` enables middle arrowheads for graph diagrams; `"end"` is the default.
The same keyword is supported by `render_rich` and `termaid.output.styled.render_styled`.
These adapters also accept `max_width` to bound edge-label placement, as the CLI does with
`--width`; this alone does not fit oversized node layouts.

### `render_rich(source, ..., theme="default") -> rich.text.Text`

Render as a [Rich](https://rich.readthedocs.io/) `Text` object with colors. Requires `pip install termaid[rich]`.

### `MermaidWidget`

A [Textual](https://textual.textualize.io/) widget with a reactive `source` attribute. Requires `pip install termaid[textual]`. Updates live when you change the `source` property.

```python
from termaid import MermaidWidget

class MyApp(App):
    def compose(self):
        yield MermaidWidget("graph LR\n  A --> B")
```

## Themes

11 built-in themes for `--theme` / `render_rich()`. Run `termaid --themes` to list them.

**Text themes** (foreground colors only):

| Theme | Colors | Description |
|-------|--------|-------------|
| `default` | ![#00FFFF](https://placehold.co/12x12/00FFFF/00FFFF.png) ![#FFFF00](https://placehold.co/12x12/FFFF00/FFFF00.png) ![#FFFFFF](https://placehold.co/12x12/FFFFFF/FFFFFF.png) | Cyan nodes, yellow arrows, white labels |
| `terra` | ![#D4845A](https://placehold.co/12x12/D4845A/D4845A.png) ![#E8A87C](https://placehold.co/12x12/E8A87C/E8A87C.png) ![#F5E6D3](https://placehold.co/12x12/F5E6D3/F5E6D3.png) | Warm earth tones (browns, oranges) |
| `neon` | ![#FF00FF](https://placehold.co/12x12/FF00FF/FF00FF.png) ![#00FF00](https://placehold.co/12x12/00FF00/00FF00.png) ![#00FFFF](https://placehold.co/12x12/00FFFF/00FFFF.png) | Magenta nodes, green arrows, cyan edges |
| `mono` | ![#FFFFFF](https://placehold.co/12x12/FFFFFF/FFFFFF.png) ![#AAAAAA](https://placehold.co/12x12/AAAAAA/AAAAAA.png) ![#666666](https://placehold.co/12x12/666666/666666.png) | White/gray monochrome |
| `amber` | ![#FFB000](https://placehold.co/12x12/FFB000/FFB000.png) ![#FFD080](https://placehold.co/12x12/FFD080/FFD080.png) ![#FFD580](https://placehold.co/12x12/FFD580/FFD580.png) | Amber/gold CRT-style |
| `phosphor` | ![#33FF33](https://placehold.co/12x12/33FF33/33FF33.png) ![#66FF66](https://placehold.co/12x12/66FF66/66FF66.png) ![#AAFFAA](https://placehold.co/12x12/AAFFAA/AAFFAA.png) | Green phosphor terminal-style |

**Solid themes** (filled backgrounds with foreground colors):

| Theme | Colors | Description |
|-------|--------|-------------|
| `gruvbox` | ![#282828](https://placehold.co/12x12/282828/282828.png) ![#FABD2F](https://placehold.co/12x12/FABD2F/FABD2F.png) ![#FE8019](https://placehold.co/12x12/FE8019/FE8019.png) | Gruvbox dark palette |
| `monokai` | ![#272822](https://placehold.co/12x12/272822/272822.png) ![#F92672](https://placehold.co/12x12/F92672/F92672.png) ![#A6E22E](https://placehold.co/12x12/A6E22E/A6E22E.png) | Monokai dark with pink/green accents |
| `dracula` | ![#282A36](https://placehold.co/12x12/282A36/282A36.png) ![#BD93F9](https://placehold.co/12x12/BD93F9/BD93F9.png) ![#50FA7B](https://placehold.co/12x12/50FA7B/50FA7B.png) | Dracula purple/pink/green palette |
| `nord` | ![#2E3440](https://placehold.co/12x12/2E3440/2E3440.png) ![#88C0D0](https://placehold.co/12x12/88C0D0/88C0D0.png) ![#A3BE8C](https://placehold.co/12x12/A3BE8C/A3BE8C.png) | Nord muted blue/cyan arctic palette |
| `solarized` | ![#002B36](https://placehold.co/12x12/002B36/002B36.png) ![#268BD2](https://placehold.co/12x12/268BD2/268BD2.png) ![#B58900](https://placehold.co/12x12/B58900/B58900.png) | Solarized dark blue/yellow/cyan |

## Optional extras

```bash
pip install termaid[rich]      # Colored terminal output
pip install termaid[textual]   # Textual TUI widget
```

## Limitations

- **Layout engine is approximate.** Node positioning uses a grid-based barycenter heuristic. Very dense graphs may still produce some edge crossings.
- **Manhattan-only edge routing.** Edges use A* pathfinding on a grid. The engine auto-expands gaps for crossing edges and biases toward flow-aligned routes.
- **Wide diagrams.** The CLI auto-compacts when the diagram exceeds terminal width. For very wide LR chains, use `--width N`, `--gap 1`, or pipe through `less -S`.

## Gallery

See the [examples page](https://fasouto.github.io/termaid-web/examples.html) for rendered examples of all 18 supported diagram types.

## Acknowledgements

Inspired by [mermaid-ascii](https://github.com/AlexanderGrooff/mermaid-ascii) by Alexander Grooff and [beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) by Lukilabs.

## License

MIT
