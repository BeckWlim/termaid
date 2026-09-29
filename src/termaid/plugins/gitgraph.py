"""Gitgraph diagrams: models, parsing, layout, and drawing."""
from __future__ import annotations

from termaid.core.contracts import ParsedSource, RenderConfig, RenderResult

from dataclasses import dataclass, field
import json
import re
from termaid.core.canvas import Canvas
from termaid.renderer.charset import ASCII, UNICODE, CharSet
from termaid.utils import display_width


# Model
# ------------------------------------------------------------------------

@dataclass
class Commit:
    id: str
    branch: str
    type: str = "NORMAL"  # "NORMAL", "REVERSE", "HIGHLIGHT"
    tag: str = ""
    parents: list[str] = field(default_factory=list)
    seq: int = 0


@dataclass
class Branch:
    name: str
    order: int = -1
    start_commit: str = ""


@dataclass
class GitGraph:
    commits: list[Commit] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    direction: str = "LR"
    main_branch_name: str = "main"
    warnings: list[str] = field(default_factory=list)


# Parsing
# ------------------------------------------------------------------------

def parse_git_graph(text: str) -> GitGraph:
    """Parse mermaid gitGraph text into a GitGraph model."""
    parser = _GitGraphParser(text)
    return parser.parse()


class _GitGraphParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.diagram = GitGraph()
        self.current_branch = "main"
        self.branch_heads: dict[str, str] = {}
        self.auto_id = 0
        self._commit_map: dict[str, Commit] = {}
        self._branch_set: set[str] = set()
        self._seq = 0

    def parse(self) -> GitGraph:
        lines = self._preprocess(self.text)
        if not lines:
            return self.diagram

        # Handle %%{init}%% directives before the header
        remaining: list[str] = []
        for line in lines:
            if line.startswith("%%{init"):
                self._parse_init(line)
            else:
                remaining.append(line)

        if not remaining:
            return self.diagram

        # Parse header
        header = remaining[0]
        if header.startswith("gitGraph"):
            rest = header[len("gitGraph"):].strip()
            # Check for direction: "gitGraph TB:" or "gitGraph LR:"
            dir_match = re.match(r"(LR|TB|BT)\s*:?", rest, re.IGNORECASE)
            if dir_match:
                self.diagram.direction = dir_match.group(1).upper()
            remaining = remaining[1:]

        # Update current_branch from config
        self.current_branch = self.diagram.main_branch_name

        # Ensure main branch exists
        self._ensure_branch(self.current_branch)

        for line in remaining:
            self._parse_line(line)

        return self.diagram

    def _preprocess(self, text: str) -> list[str]:
        """Split into lines, strip inline comments and blank lines."""
        result: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            # Skip pure comment lines (but keep %%{init} directives)
            if stripped.startswith("%%") and not stripped.startswith("%%{"):
                continue
            if stripped:
                result.append(stripped)
        return result

    def _parse_init(self, line: str) -> None:
        """Extract config from %%{init: {...}}%% directive."""
        m = re.search(r"%%\{init:\s*(\{.*\})\s*\}%%", line)
        if not m:
            return
        try:
            config = json.loads(m.group(1))
        except json.JSONDecodeError:
            # Try with single quotes replaced
            try:
                fixed = m.group(1).replace("'", '"')
                config = json.loads(fixed)
            except json.JSONDecodeError:
                return
        git_config = config.get("gitGraph", config)
        if "mainBranchName" in git_config:
            self.diagram.main_branch_name = git_config["mainBranchName"]
        if "mainBranchOrder" in git_config:
            # Will be applied when we create the main branch
            pass

    def _parse_line(self, line: str) -> None:
        # commit
        if line.startswith("commit"):
            self._parse_commit(line)
            return

        # branch
        if line.startswith("branch "):
            self._parse_branch(line)
            return

        # checkout / switch
        if line.startswith("checkout ") or line.startswith("switch "):
            parts = line.split(None, 1)
            if len(parts) >= 2:
                branch_name = parts[1].strip().strip('"')
                if branch_name in self._branch_set:
                    self.current_branch = branch_name
                else:
                    self.diagram.warnings.append(
                        f"Checkout non-existent branch: {branch_name!r}"
                    )
            return

        # merge
        if line.startswith("merge "):
            self._parse_merge(line)
            return

        # cherry-pick
        if line.startswith("cherry-pick"):
            self._parse_cherry_pick(line)
            return

        # reset
        if line.startswith("reset "):
            self._parse_reset(line)
            return

        # Unrecognized line
        self.diagram.warnings.append(f"Unrecognized line: {line!r}")

    def _parse_commit(self, line: str) -> None:
        """Parse a commit line with optional id, type, tag attributes."""
        commit_id = None
        commit_type = "NORMAL"
        tag = ""

        # Extract id: "..."
        id_match = re.search(r'id:\s*"([^"]*)"', line)
        if id_match:
            commit_id = id_match.group(1)

        # Extract type: NORMAL|REVERSE|HIGHLIGHT
        type_match = re.search(r'type:\s*(NORMAL|REVERSE|HIGHLIGHT)', line)
        if type_match:
            commit_type = type_match.group(1)

        # Extract tag: "..."
        tag_match = re.search(r'tag:\s*"([^"]*)"', line)
        if tag_match:
            tag = tag_match.group(1)

        if commit_id is None:
            commit_id = str(self.auto_id)
            self.auto_id += 1

        parents = []
        if self.current_branch in self.branch_heads:
            parents.append(self.branch_heads[self.current_branch])

        commit = Commit(
            id=commit_id,
            branch=self.current_branch,
            type=commit_type,
            tag=tag,
            parents=parents,
            seq=self._seq,
        )
        self._seq += 1
        self.diagram.commits.append(commit)
        self._commit_map[commit_id] = commit
        self.branch_heads[self.current_branch] = commit_id

    def _parse_branch(self, line: str) -> None:
        """Parse a branch line: branch <name> [order: N]."""
        m = re.match(r'branch\s+"?([^"]+?)"?\s*(?:order:\s*(\d+))?\s*$', line)
        if not m:
            return
        name = m.group(1).strip()
        order = int(m.group(2)) if m.group(2) else -1

        start_commit = self.branch_heads.get(self.current_branch, "")
        self._ensure_branch(name, order=order, start_commit=start_commit)

        # Copy head from current branch so the new branch forks from here
        if self.current_branch in self.branch_heads:
            self.branch_heads[name] = self.branch_heads[self.current_branch]

        self.current_branch = name

    def _parse_merge(self, line: str) -> None:
        """Parse a merge line: merge <branch> [id: "..."] [type: ...] [tag: "..."]."""
        m = re.match(r'merge\s+"?([^"]+?)"?(?:\s|$)', line)
        if not m:
            return
        merged_branch = m.group(1).strip()

        commit_id = None
        commit_type = "NORMAL"
        tag = ""

        id_match = re.search(r'id:\s*"([^"]*)"', line)
        if id_match:
            commit_id = id_match.group(1)

        type_match = re.search(r'type:\s*(NORMAL|REVERSE|HIGHLIGHT)', line)
        if type_match:
            commit_type = type_match.group(1)

        tag_match = re.search(r'tag:\s*"([^"]*)"', line)
        if tag_match:
            tag = tag_match.group(1)

        if commit_id is None:
            commit_id = str(self.auto_id)
            self.auto_id += 1

        parents = []
        if self.current_branch in self.branch_heads:
            parents.append(self.branch_heads[self.current_branch])
        if merged_branch in self.branch_heads:
            parents.append(self.branch_heads[merged_branch])

        commit = Commit(
            id=commit_id,
            branch=self.current_branch,
            type=commit_type,
            tag=tag,
            parents=parents,
            seq=self._seq,
        )
        self._seq += 1
        self.diagram.commits.append(commit)
        self._commit_map[commit_id] = commit
        self.branch_heads[self.current_branch] = commit_id

    def _parse_cherry_pick(self, line: str) -> None:
        """Parse a cherry-pick line: cherry-pick id: "<id>"."""
        m = re.search(r'id:\s*"([^"]*)"', line)
        if not m:
            return
        source_id = m.group(1)

        if source_id not in self._commit_map:
            self.diagram.warnings.append(
                f"Cherry-pick non-existent commit: {source_id!r}"
            )
            return

        commit_id = f"{source_id}-cherry"
        # Avoid duplicate IDs
        while commit_id in self._commit_map:
            commit_id += "-cp"

        tag = ""
        tag_match = re.search(r'tag:\s*"([^"]*)"', line)
        if tag_match:
            tag = tag_match.group(1)

        parents = []
        if self.current_branch in self.branch_heads:
            parents.append(self.branch_heads[self.current_branch])
        parents.append(source_id)

        commit = Commit(
            id=commit_id,
            branch=self.current_branch,
            type="NORMAL",
            tag=tag,
            parents=parents,
            seq=self._seq,
        )
        self._seq += 1
        self.diagram.commits.append(commit)
        self._commit_map[commit_id] = commit
        self.branch_heads[self.current_branch] = commit_id

    def _parse_reset(self, line: str) -> None:
        """Parse reset line: reset <ref>[~<N>]."""
        m = re.match(r'reset\s+"?([^"~]+?)"?\s*(?:~(\d+))?\s*$', line)
        if not m:
            return
        ref = m.group(1).strip()
        ancestor = int(m.group(2)) if m.group(2) else 0

        # Resolve ref → commit id
        if ref in self.branch_heads:
            commit_id = self.branch_heads[ref]
        elif ref in self._commit_map:
            commit_id = ref
        else:
            self.diagram.warnings.append(f"Reset to unknown ref: {ref!r}")
            return

        # Walk back N ancestors
        for _ in range(ancestor):
            commit = self._commit_map.get(commit_id)
            if commit and commit.parents:
                commit_id = commit.parents[0]
            else:
                self.diagram.warnings.append(
                    f"Cannot walk back {ancestor} ancestors from {ref!r}"
                )
                return

        # Move current branch HEAD
        self.branch_heads[self.current_branch] = commit_id

    def _ensure_branch(
        self, name: str, order: int = -1, start_commit: str = ""
    ) -> None:
        """Add a branch if it doesn't exist yet."""
        if name not in self._branch_set:
            self._branch_set.add(name)
            self.diagram.branches.append(
                Branch(name=name, order=order, start_commit=start_commit)
            )


# Layout and drawing
# ------------------------------------------------------------------------

# ── layout constants ──────────────────────────────────────────────
_MIN_COMMIT_GAP = 6  # minimum horizontal gap between commit markers
_BRANCH_GAP = 2      # vertical gap between branch lines
_MARGIN = 2           # canvas margin
_LABEL_PAD = 2        # padding between adjacent commit labels

# Commit markers
_MARKER_NORMAL = "●"
_MARKER_REVERSE = "✖"
_MARKER_HIGHLIGHT = "■"
_MARKER_NORMAL_ASCII = "o"
_MARKER_REVERSE_ASCII = "X"
_MARKER_HIGHLIGHT_ASCII = "#"


def _get_marker(commit_type: str, use_ascii: bool) -> str:
    if use_ascii:
        return {
            "NORMAL": _MARKER_NORMAL_ASCII,
            "REVERSE": _MARKER_REVERSE_ASCII,
            "HIGHLIGHT": _MARKER_HIGHLIGHT_ASCII,
        }.get(commit_type, _MARKER_NORMAL_ASCII)
    return {
        "NORMAL": _MARKER_NORMAL,
        "REVERSE": _MARKER_REVERSE,
        "HIGHLIGHT": _MARKER_HIGHLIGHT,
    }.get(commit_type, _MARKER_NORMAL)


def _sort_branches(diagram: GitGraph) -> list[str]:
    """Sort branches: main first, then by explicit order, then by appearance."""
    ordered: list[tuple[int, int, str]] = []
    for i, b in enumerate(diagram.branches):
        if b.name == diagram.main_branch_name:
            sort_key = -2
        elif b.order >= 0:
            sort_key = b.order
        else:
            sort_key = 1000 + i
        ordered.append((sort_key, i, b.name))
    ordered.sort()
    return [name for _, _, name in ordered]


def _commit_footprint(c: Commit) -> int:
    """Return the half-width of the widest label (id or tag) for a commit."""
    w = len(c.id)
    if c.tag:
        w = max(w, len(c.tag) + 2)  # "[tag]"
    return (w + 1) // 2  # ceil half


def _compute_branch_extents_lr(
    diagram: GitGraph,
    branch_commits: dict[str, list[Commit]],
    commit_col: dict[str, int],
    commit_map: dict[str, Commit],
    main_branch: str,
    line_start_col: int,
) -> dict[str, tuple[int, int]]:
    """Compute (start_col, end_col) for each branch line in LR mode.

    Extends branch lines to cover fork and merge points.
    """
    extents: dict[str, tuple[int, int]] = {}

    for name, commits in branch_commits.items():
        if not commits:
            continue
        first_col = commit_col[commits[0].id]
        last_col = commit_col[commits[-1].id]

        if name == main_branch:
            start = line_start_col
        else:
            start = first_col
        end = last_col + 1
        extents[name] = (start, end)

    # Extend branches to cover merge/fork points
    for c in diagram.commits:
        for parent_id in c.parents:
            if parent_id not in commit_map:
                continue
            parent = commit_map[parent_id]
            if parent.branch != c.branch and parent.branch in extents:
                merge_col = commit_col[c.id]
                old_start, old_end = extents[parent.branch]
                extents[parent.branch] = (old_start, max(old_end, merge_col))

    return extents


def _compute_layout_lr(
    diagram: GitGraph, use_ascii: bool
) -> tuple[dict[str, int], dict[str, int], list[str], int, int, int]:
    """Compute LR layout with adaptive per-commit spacing.

    Returns (commit_col, branch_row, sorted_branches, canvas_width, canvas_height, left_offset).
    """
    sorted_branches = _sort_branches(diagram)
    branch_row: dict[str, int] = {}

    row_height = _BRANCH_GAP + 1
    for i, name in enumerate(sorted_branches):
        branch_row[name] = _MARGIN + i * row_height

    branch_label_width = 0
    for name in sorted_branches:
        branch_label_width = max(branch_label_width, len(name))
    left_offset = _MARGIN + branch_label_width + 2

    # Adaptive per-commit column placement:
    # Each commit needs enough space so its label doesn't overlap the previous.
    commits = diagram.commits
    commit_col: dict[str, int] = {}

    if commits:
        # First commit: place at left_offset + its own half-width
        fp0 = _commit_footprint(commits[0])
        commit_col[commits[0].id] = left_offset + fp0

        for i in range(1, len(commits)):
            prev = commits[i - 1]
            curr = commits[i]
            prev_fp = _commit_footprint(prev)
            curr_fp = _commit_footprint(curr)
            # Minimum gap so labels don't overlap
            label_gap = prev_fp + _LABEL_PAD + curr_fp
            gap = max(_MIN_COMMIT_GAP, label_gap)
            commit_col[curr.id] = commit_col[prev.id] + gap

    last_col = max(commit_col.values(), default=left_offset)
    last_fp = _commit_footprint(commits[-1]) if commits else 0
    canvas_width = last_col + last_fp + _MARGIN + 1
    canvas_height = _MARGIN + len(sorted_branches) * row_height + _MARGIN

    return commit_col, branch_row, sorted_branches, canvas_width, canvas_height, left_offset


def _draw_lr(
    diagram: GitGraph,
    canvas: Canvas,
    commit_col: dict[str, int],
    branch_row: dict[str, int],
    sorted_branches: list[str],
    left_offset: int,
    cs: CharSet,
    use_ascii: bool,
) -> None:
    """Draw the gitGraph in LR orientation onto the canvas."""
    h_char = cs.line_horizontal
    v_char = cs.line_vertical

    branch_commits: dict[str, list[Commit]] = {b: [] for b in sorted_branches}
    for c in diagram.commits:
        if c.branch in branch_commits:
            branch_commits[c.branch].append(c)

    commit_map: dict[str, Commit] = {c.id: c for c in diagram.commits}

    branch_label_width = max((len(b) for b in sorted_branches), default=0)
    line_start_col = _MARGIN + branch_label_width + 1

    # Compute branch line extents (with merge/fork extensions)
    extents = _compute_branch_extents_lr(
        diagram, branch_commits, commit_col, commit_map,
        diagram.main_branch_name, line_start_col,
    )

    # 1. Draw branch name labels
    for name in sorted_branches:
        row = branch_row[name]
        canvas.put_text(row, _MARGIN, name, style="subgraph")

    # 2. Draw branch lines (horizontal)
    for name in sorted_branches:
        if name not in extents:
            continue
        row = branch_row[name]
        start, end = extents[name]
        canvas.draw_horizontal(row, start, end, h_char, style="edge")

    # 3. Draw fork and merge lines (vertical connections between branches)
    for c in diagram.commits:
        col = commit_col[c.id]
        target_row = branch_row[c.branch]

        for parent_id in c.parents:
            if parent_id not in commit_map:
                continue
            parent = commit_map[parent_id]
            if parent.branch == c.branch:
                continue

            source_row = branch_row[parent.branch]
            if source_row == target_row:
                continue

            r_min = min(source_row, target_row)
            r_max = max(source_row, target_row)
            for r in range(r_min, r_max + 1):
                canvas.put(r, col, v_char, style="edge")

    # 4. Draw commit markers and labels (LAST so they are visible)
    for c in diagram.commits:
        col = commit_col[c.id]
        row = branch_row[c.branch]
        marker = _get_marker(c.type, use_ascii)

        canvas.put(row, col, marker, merge=False, style="node")

        label = c.id
        label_col = col - display_width(label) // 2
        canvas.put_text(row + 1, label_col, label, style="label")

        if c.tag:
            tag_text = f"[{c.tag}]"
            tag_col = col - display_width(tag_text) // 2
            canvas.put_text(row - 1, tag_col, tag_text, style="edge_label")


def _draw_tb(
    diagram: GitGraph,
    canvas: Canvas,
    use_ascii: bool,
    cs: CharSet,
    *,
    bottom_to_top: bool = False,
) -> None:
    """Draw the gitGraph in TB (or BT) orientation onto the canvas."""
    h_char = cs.line_horizontal
    v_char = cs.line_vertical

    sorted_branches = _sort_branches(diagram)

    branch_commits: dict[str, list[Commit]] = {b: [] for b in sorted_branches}
    for c in diagram.commits:
        if c.branch in branch_commits:
            branch_commits[c.branch].append(c)

    commit_map: dict[str, Commit] = {c.id: c for c in diagram.commits}

    # Compute column gap based on max label width
    max_label = 0
    for b in sorted_branches:
        max_label = max(max_label, len(b))
    for c in diagram.commits:
        max_label = max(max_label, len(c.id))
        if c.tag:
            max_label = max(max_label, len(c.tag) + 2)

    col_gap = max(max_label + 4, 10)

    branch_col: dict[str, int] = {}
    for i, name in enumerate(sorted_branches):
        branch_col[name] = _MARGIN + i * col_gap

    row_gap = 4
    n_commits = len(diagram.commits)
    label_margin = 2

    if bottom_to_top:
        bottom_label_row_offset = _MARGIN + n_commits * row_gap + label_margin
        canvas_h = bottom_label_row_offset + 2 + _MARGIN

        commit_row: dict[str, int] = {}
        for i, c in enumerate(diagram.commits):
            commit_row[c.id] = _MARGIN + (n_commits - 1 - i) * row_gap + 2
    else:
        top_offset = _MARGIN + 2
        canvas_h = top_offset + n_commits * row_gap + _MARGIN

        commit_row = {}
        for i, c in enumerate(diagram.commits):
            commit_row[c.id] = top_offset + i * row_gap

    canvas_w = _MARGIN + len(sorted_branches) * col_gap + _MARGIN
    canvas.__init__(canvas_w, canvas_h)  # type: ignore[misc]

    # Compute vertical branch extents (with merge extensions)
    branch_start: dict[str, int] = {}
    branch_end: dict[str, int] = {}
    for name, commits in branch_commits.items():
        if not commits:
            continue
        rows = [commit_row[c.id] for c in commits]
        min_row = min(rows)
        max_row = max(rows)
        if name == diagram.main_branch_name:
            if bottom_to_top:
                branch_start[name] = min_row - 1
                branch_end[name] = bottom_label_row_offset - 1
            else:
                branch_start[name] = _MARGIN + 1
                branch_end[name] = max_row + 1
        else:
            branch_start[name] = min_row
            branch_end[name] = max_row + 1

    # Extend branches to cover merge points
    for c in diagram.commits:
        for parent_id in c.parents:
            if parent_id not in commit_map:
                continue
            parent = commit_map[parent_id]
            if parent.branch != c.branch and parent.branch in branch_end:
                merge_row = commit_row[c.id]
                branch_start[parent.branch] = min(
                    branch_start[parent.branch], merge_row
                )
                branch_end[parent.branch] = max(
                    branch_end[parent.branch], merge_row
                )

    # 1. Draw branch name labels
    if bottom_to_top:
        label_row = bottom_label_row_offset
    else:
        label_row = _MARGIN
    for name in sorted_branches:
        col = branch_col[name]
        label_col = col - len(name) // 2
        canvas.put_text(label_row, label_col, name, style="subgraph")

    # 2. Draw branch lines (vertical)
    for name in sorted_branches:
        if name not in branch_start:
            continue
        col = branch_col[name]
        canvas.draw_vertical(
            col, branch_start[name], branch_end[name], v_char, style="edge"
        )

    # 3. Draw fork/merge lines (horizontal connections) BEFORE markers
    for c in diagram.commits:
        row = commit_row[c.id]
        target_col = branch_col[c.branch]

        for parent_id in c.parents:
            if parent_id not in commit_map:
                continue
            parent = commit_map[parent_id]
            if parent.branch == c.branch:
                continue

            source_col = branch_col[parent.branch]
            if source_col == target_col:
                continue

            c_min = min(source_col, target_col)
            c_max = max(source_col, target_col)
            for cc in range(c_min, c_max + 1):
                canvas.put(row, cc, h_char, style="edge")

    # 4. Draw commit markers and labels LAST
    for c in diagram.commits:
        row = commit_row[c.id]
        col = branch_col[c.branch]
        marker = _get_marker(c.type, use_ascii)

        canvas.put(row, col, marker, merge=False, style="node")

        label_col = col - len(c.id) // 2
        if bottom_to_top:
            canvas.put_text(row - 1, label_col, c.id, style="label")
            if c.tag:
                tag_text = f"[{c.tag}]"
                tag_col = col - display_width(tag_text) // 2
                canvas.put_text(row + 1, tag_col, tag_text, style="edge_label")
        else:
            canvas.put_text(row + 1, label_col, c.id, style="label")
            if c.tag:
                tag_text = f"[{c.tag}]"
                tag_col = col - display_width(tag_text) // 2
                canvas.put_text(row - 1, tag_col, tag_text, style="edge_label")


def render_git_graph(diagram: GitGraph, *, use_ascii: bool = False) -> Canvas:
    """Render a GitGraph to a Canvas."""
    cs = ASCII if use_ascii else UNICODE

    if not diagram.commits:
        return Canvas(1, 1)

    if diagram.direction in ("TB", "BT"):
        canvas = Canvas(1, 1)
        _draw_tb(
            diagram, canvas, use_ascii, cs,
            bottom_to_top=(diagram.direction == "BT"),
        )
        return canvas

    # LR (default)
    commit_col, branch_row, sorted_branches, width, height, left_offset = (
        _compute_layout_lr(diagram, use_ascii)
    )
    canvas = Canvas(width, height)
    _draw_lr(
        diagram, canvas, commit_col, branch_row, sorted_branches,
        left_offset, cs, use_ascii,
    )
    return canvas


def render(source: ParsedSource, config: RenderConfig) -> RenderResult:
    text = source.text
    canvas = render_git_graph(parse_git_graph(text), use_ascii=config.use_ascii)
    return RenderResult(canvas)
