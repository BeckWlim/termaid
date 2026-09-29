"""Rich renderable output adapter (optional dependency)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from termaid.core.canvas import DiagramPlan
from termaid.renderer.themes import Theme, get_theme

if TYPE_CHECKING:
    from rich.text import Text


def _hex_to_rich_color(hex_color: str) -> str | None:
    """Convert a hex color (#fff or #ffffff) to a Rich color string."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        return f"#{h}"
    return None


def _css_to_rich_style(props: dict[str, str]) -> str | None:
    """Convert CSS-like properties to a Rich style string."""
    parts: list[str] = []

    # fill/background-color → on color
    fill = props.get("fill") or props.get("background-color") or props.get("background")
    if fill:
        color = _hex_to_rich_color(fill)
        if color:
            parts.append(f"on {color}")

    # stroke/color → foreground color
    stroke = props.get("stroke") or props.get("color")
    if stroke:
        color = _hex_to_rich_color(stroke)
        if color:
            parts.append(color)

    # stroke-width → bold if thick
    sw = props.get("stroke-width")
    if sw and sw.replace("px", "").strip() not in ("0", "1", ""):
        parts.append("bold")

    # stroke-dasharray → dim for dashed
    if props.get("stroke-dasharray"):
        parts.append("dim")

    return " ".join(parts) if parts else None


def _style_map(diagram: DiagramPlan, theme: Theme) -> dict[str, str]:
    styles = {
        "node": theme.node, "edge": theme.edge, "arrow": theme.arrow,
        "label": theme.label, "edge_label": theme.edge_label, "default": theme.default,
    }
    if diagram.graph_based:
        styles.update({
            "subgraph": theme.subgraph, "subgraph_label": theme.subgraph_label,
            "bold_label": f"bold {theme.label}", "italic_label": f"italic {theme.label}",
        })
        for rule in diagram.styles:
            rich_style = _css_to_rich_style(dict(rule.properties))
            if rich_style:
                styles[rule.key] = rich_style
    else:
        for index, base_hex in enumerate(theme.section_colors):
            styles[f"section:{index}"] = f"bold white on {base_hex}"
            red, green, blue = (int(base_hex[offset:offset + 2], 16) for offset in (1, 3, 5))
            light_hex = f"#{min(255, red + 30):02X}{min(255, green + 30):02X}{min(255, blue + 30):02X}"
            styles[f"section:{index}:deep"] = f"bold white on {light_hex}"
            bright_hex = f"#{min(255, red * 3):02X}{min(255, green * 3):02X}{min(255, blue * 3):02X}"
            styles[f"sectionfg:{index}"] = f"bold {bright_hex}"
    return styles


def _cell_style(character: str, key: str, styles: dict[str, str],
                theme: Theme, graph_based: bool) -> str:
    foreground = styles.get(key, "") if character != " " else ""
    if not theme.is_solid:
        return styles.get(key, "") if character != " " or key.startswith("section:") else ""
    if key.startswith("sectionfg:"):
        return foreground
    if not graph_based:
        if key.startswith("section:"):
            return styles.get(key, styles.get(key.split(":deep")[0], theme.bg_default))
        if key not in ("node", "label"):
            return foreground
        background = theme.bg_node
    elif key in ("node", "label", "bold_label", "italic_label") or key.startswith(("nodestyle:", "class:")):
        background = theme.bg_node
    elif key in ("subgraph", "subgraph_label"):
        background = theme.bg_subgraph
    else:
        background = theme.bg_default
    return f"{foreground} {background}".strip() if foreground else background


def serialize_rich(diagram: DiagramPlan, theme: str = "default") -> Text:
    """Serialize frozen cells, preserving each family's established style policy."""
    from rich.text import Text

    selected_theme = get_theme(theme)
    styles = _style_map(diagram, selected_theme)
    rows = diagram.to_styled_pairs()
    lines: list[str] = []
    for row in rows:
        raw_line = "".join(character for character, _ in row)
        preserve_background = not diagram.graph_based and any(key.startswith("section:") for _, key in row)
        lines.append(raw_line if preserve_background else raw_line.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    output = Text("\n".join(lines))
    offset = 0
    for row, line in zip(rows, lines):
        for column, (character, key) in enumerate(row[:len(line)]):
            style = _cell_style(character, key, styles, selected_theme, diagram.graph_based)
            if style:
                output.stylize(style, offset + column, offset + column + 1)
        offset += len(line) + 1
    return output
