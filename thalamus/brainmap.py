"""The Thalamus brain: one SVG per theme showing which lab won each job this week.

Stdlib only. `write()` produces assets/brain-map-light.svg and brain-map-dark.svg.
"""
from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1280, 760
CX, CY = 640.0, 372.0
RX, RY = 410.0, 292.0
SIDE_SPAN = 75.0  # degrees either side of 3 and 9 o'clock; top and bottom stay free for the core glow
GAP_UNITS = 0.7   # extra spacing between groups, in node-steps
CORE_R = 46.0
FONT = "ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"
GROUP_ORDER = ["Think", "Voice", "Build", "See", "Make", "Scale"]
NEUTRAL = "Other"

# lab -> (light, dark). Colors are for nodes and edges only; text stays neutral for contrast.
LAB_COLORS: dict[str, tuple[str, str]] = {
    "Anthropic": ("#c2410c", "#fb923c"),
    "OpenAI": ("#047857", "#34d399"),
    "Google": ("#1d4ed8", "#60a5fa"),
    "xAI": ("#111827", "#e5e7eb"),
    "Meta": ("#7c3aed", "#a78bfa"),
    "DeepSeek": ("#4338ca", "#818cf8"),
    "Moonshot AI": ("#7e22ce", "#c084fc"),
    "Alibaba (Qwen)": ("#a16207", "#facc15"),
    "Zhipu (Z.ai)": ("#be185d", "#f472b6"),
    "Xiaomi": ("#b91c1c", "#f87171"),
    "MiniMax": ("#0f766e", "#2dd4bf"),
    "Mistral": ("#d97706", "#fbbf24"),
    "ByteDance": ("#a21caf", "#e879f9"),
    "Black Forest Labs": ("#374151", "#9ca3af"),
    "Kuaishou (Kling)": ("#15803d", "#4ade80"),
    "Runway": ("#9d174d", "#fb7185"),
    "Luma": ("#0e7490", "#22d3ee"),
    "Alibaba": ("#854d0e", "#fde047"),
    NEUTRAL: ("#6b7280", "#8b949e"),
}

THEMES = {
    "light": {"bg": "#ffffff", "text": "#1f2328", "muted": "#59636e", "faint": "#d0d7de", "glow": "#6366f1"},
    "dark": {"bg": "#0d1117", "text": "#e6edf3", "muted": "#9198a1", "faint": "#30363d", "glow": "#818cf8"},
}


def shorten(text: str, limit: int) -> str:
    """Cut at a word boundary, with plain "..." when something was dropped."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    room = limit - 3
    cut = text[:room]
    if text[room] != " " and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "..."


def lab_color(lab: str | None, theme: str) -> str:
    pair = LAB_COLORS.get(lab or "", LAB_COLORS[NEUTRAL])
    return pair[1 if theme == "dark" else 0]


def _winner(job: dict) -> tuple[str | None, str | None]:
    """(pick name, lab) of the best pick, or (None, None) when the job has no data."""
    best = (job.get("picks") or {}).get("best")
    if not best:
        return None, None
    lab = next((r.get("lab") for r in job.get("top") or [] if r.get("id") == best.get("id")), None)
    return best.get("name") or best.get("id"), lab or NEUTRAL


def _ordered(payload: dict, jobs_meta: list[dict]) -> list[tuple[str, dict, str]]:
    """(job_id, payload job, group) in group order, then meta order, then leftovers by id."""
    jobs = payload.get("jobs") or {}
    ids = [m["id"] for m in jobs_meta if m["id"] in jobs]
    known = set(ids)
    ids += sorted(k for k in jobs if k not in known)
    group_of = {m["id"]: m.get("group") for m in jobs_meta}
    rows = [(k, jobs[k], jobs[k].get("group") or group_of.get(k) or "Think") for k in ids]
    rank = {g: i for i, g in enumerate(GROUP_ORDER)}
    return sorted(rows, key=lambda r: rank.get(r[2], len(rank)))  # stable: keeps meta order inside a group


def _layout(rows: list[tuple[str, dict, str]]) -> list[dict]:
    """Place nodes down the right side, then up the left, clockwise from the top right.

    Labels are horizontal, so nodes stay on the two flanks; spread along the top
    or bottom of the ellipse they would sit closer together than a label is wide.
    """
    right = (len(rows) + 1) // 2
    placed: list[dict] = []
    for side, chunk in (("R", rows[:right]), ("L", rows[right:])):
        units, u = [], 0.0
        for i, (_, _, grp) in enumerate(chunk):
            if i and chunk[i - 1][2] != grp:
                u += GAP_UNITS
            units.append(u)
            u += 1.0
        top = (units[-1] if units else 0.0) or 1.0
        for (jid, job, grp), un in zip(chunk, units):
            # even steps in y, not in angle: angle steps bunch up near the top and bottom
            v = 2 * (un / top) - 1 if len(chunk) > 1 else 0.0
            t = math.degrees(math.asin(v * math.sin(math.radians(SIDE_SPAN))))
            theta = math.radians(t if side == "R" else 180.0 - t)
            placed.append({"id": jid, "job": job, "group": grp, "side": side,
                           "x": CX + RX * math.cos(theta), "y": CY + RY * math.sin(theta)})
    return placed


def _printable(text: str) -> str:
    """Control characters make the SVG unparsable (a broken image in the README), so they go."""
    return "".join(ch for ch in str(text) if ch.isprintable())


def _t(x: float, y: float, text: str, fill: str, size: int, anchor: str = "start",
       weight: str = "400", extra: str = "") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(_printable(text))}</text>')


def _edge(x: float, y: float) -> str:
    dx = x - CX
    sx = CX + math.copysign(CORE_R * 0.9, dx)
    return f"M{sx:.1f},{CY:.1f} C{CX + dx * 0.45:.1f},{CY:.1f} {CX + dx * 0.55:.1f},{y:.1f} {x:.1f},{y:.1f}"


def _node(p: dict, theme: str, pal: dict) -> tuple[str, str]:
    """(edge svg, node and label svg) for one job."""
    name, lab = _winner(p["job"])
    x, y, right = p["x"], p["y"], p["side"] == "R"
    title = shorten(p["job"].get("short") or p["job"].get("title") or p["id"], 28)
    anchor, tx = ("start", x + 18) if right else ("end", x - 18)
    if name is None:
        edge = (f'<path d="{_edge(x, y)}" fill="none" stroke="{pal["muted"]}" stroke-width="1.2" '
                f'stroke-dasharray="3 5" opacity="0.55"/>')
        dot = (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{pal["bg"]}" stroke="{pal["muted"]}" '
               f'stroke-width="1.6" opacity="0.8"/>')
        sub = "no data yet"
    else:
        c = lab_color(lab, theme)
        edge = f'<path d="{_edge(x, y)}" fill="none" stroke="{c}" stroke-width="1.8" opacity="0.5"/>'
        dot = (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" fill="{c}" opacity="0.16"/>'
               f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{c}" stroke="{pal["bg"]}" stroke-width="2"/>')
        sub = shorten(name, 30)
    label = (_t(tx, y - 2, title, pal["text"], 13, anchor, "600")
             + _t(tx, y + 13, sub, pal["muted"], 12, anchor))
    return edge, dot + label


def _group_brackets(placed: list[dict], pal: dict) -> str:
    out: list[str] = []
    for side in ("R", "L"):
        run: list[dict] = []
        for p in [q for q in placed if q["side"] == side] + [None]:
            if run and (p is None or p["group"] != run[0]["group"]):
                y0, y1 = min(q["y"] for q in run) - 12, max(q["y"] for q in run) + 12
                lx, tx, rot = (1268, 1252, 90) if side == "R" else (12, 28, -90)
                mid = (y0 + y1) / 2
                out.append(f'<line x1="{lx}" y1="{y0:.1f}" x2="{lx}" y2="{y1:.1f}" stroke="{pal["faint"]}" '
                           f'stroke-width="2" stroke-linecap="round"/>')
                out.append(_t(tx, mid + 4, run[0]["group"].upper(), pal["muted"], 12, "middle", "700",
                              f' letter-spacing="2" transform="rotate({rot} {tx} {mid:.1f})"'))
                run = []
            if p is not None:
                run.append(p)
    return "".join(out)


def _legend(placed: list[dict], theme: str, pal: dict) -> str:
    counts: dict[str, int] = {}
    for p in placed:
        lab = _winner(p["job"])[1]
        if lab:
            counts[lab] = counts.get(lab, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not items:
        return ""
    widths = [32 + 7.2 * (len(lab) + 2) + 14 for lab, _ in items]
    rows: list[list[int]] = [[]]
    for i, w in enumerate(widths):
        if rows[-1] and sum(widths[j] for j in rows[-1]) + w > 1180:
            rows.append([])
        rows[-1].append(i)
    out, y0 = [], (722 if len(rows) == 1 else 706)
    for r, idxs in enumerate(rows):
        x = CX - sum(widths[j] for j in idxs) / 2
        y = y0 + r * 24
        for j in idxs:
            lab, n = items[j]
            out.append(f'<circle cx="{x + 6:.1f}" cy="{y - 4:.1f}" r="6" fill="{lab_color(lab, theme)}"/>')
            out.append(_t(x + 18, y, lab, pal["text"], 13, "start", "500")
                       + _t(x + 18 + 7.2 * len(lab) + 8, y, str(n), pal["muted"], 13))
            x += widths[j]
    return "".join(out)


def _core(updated: str, pal: dict) -> str:
    rings = "".join(
        f'<circle cx="{CX}" cy="{CY}" r="{r}" fill="none" stroke="{pal["glow"]}" stroke-width="1" opacity="{o}"/>'
        for r, o in ((62, 0.28), (80, 0.16), (100, 0.08)))
    return (f'<circle cx="{CX}" cy="{CY}" r="150" fill="url(#halo)"/>{rings}'
            f'<circle cx="{CX}" cy="{CY}" r="{CORE_R}" fill="url(#core)"/>'
            f'<circle cx="{CX}" cy="{CY}" r="{CORE_R}" fill="none" stroke="{pal["glow"]}" stroke-width="1.5" opacity="0.7"/>'
            + _t(CX, CY + 4, "THALAMUS", "#ffffff", 12, "middle", "800", ' letter-spacing="1.5"')
            + _t(CX, CY + CORE_R + 34, f"week of {updated}", pal["muted"], 13, "middle", "500",
                 f' stroke="{pal["bg"]}" stroke-width="4" paint-order="stroke" stroke-linejoin="round"'))


def render_svg(payload: dict, jobs_meta: list[dict], theme: str = "light") -> str:
    """Return the full brain-map SVG for one theme. Pure: inputs are not modified."""
    theme = "dark" if theme == "dark" else "light"
    pal = THEMES[theme]
    placed = _layout(_ordered(payload, jobs_meta))
    parts = [_node(p, theme, pal) for p in placed]
    glow = pal["glow"]
    guide = (f'<ellipse cx="{CX}" cy="{CY}" rx="{RX}" ry="{RY}" fill="none" stroke="{pal["faint"]}" '
             f'stroke-width="1" stroke-dasharray="2 7" opacity="0.8"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
        f'font-family="{FONT}" role="img" aria-label="Thalamus routing map: which lab won each job this week">'
        f'<defs><radialGradient id="core"><stop offset="0" stop-color="{glow}"/><stop offset="1" stop-color="#312e81"/></radialGradient>'
        f'<radialGradient id="halo"><stop offset="0" stop-color="{glow}" stop-opacity="0.38"/>'
        f'<stop offset="1" stop-color="{glow}" stop-opacity="0"/></radialGradient></defs>'
        f'<rect width="{W}" height="{H}" fill="{pal["bg"]}"/>'
        f'{guide}{_group_brackets(placed, pal)}'
        + "".join(e for e, _ in parts)
        + _core(str(payload.get("updated", "")), pal)
        + "".join(n for _, n in parts)
        + _legend(placed, theme, pal) + '</svg>\n'
    )


def write(payload: dict, jobs_meta: list[dict], out_dir: Path) -> list[Path]:
    """Write brain-map-light.svg and brain-map-dark.svg into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for theme in ("light", "dark"):
        path = out_dir / f"brain-map-{theme}.svg"
        path.write_text(render_svg(payload, jobs_meta, theme), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths
