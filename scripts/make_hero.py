"""Draw the README hero banner (assets/hero-light.svg, assets/hero-dark.svg).

Static art, regenerated only when the design changes:  python scripts/make_hero.py
Models from many labs flow into one relay in the middle and out to the jobs they fit.
"""
from __future__ import annotations

from pathlib import Path

W, H = 1280, 400
SANS = "ui-sans-serif, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
THEMES = {
    "light": {"bg": "#fafaf7", "ink": "#14161a", "muted": "#5b6270", "line": "#c3c8d2", "chip": "#ffffff",
              "chip_stroke": "#d6d9e0", "accent": "#e8590c", "accent2": "#4f46e5", "dot": "#14161a",
              "brain": "#6366f1"},
    "dark": {"bg": "#0d1117", "ink": "#f2f4f8", "muted": "#9aa3b2", "line": "#3a414d", "chip": "#161b22",
             "chip_stroke": "#30363d", "accent": "#ff8a4c", "accent2": "#a5b4fc", "dot": "#f2f4f8",
             "brain": "#818cf8"},
}
INPUTS = ["claude", "gpt", "gemini", "grok", "kimi", "deepseek", "qwen", "glm", "mimo", "muse"]
OUTPUTS = ["strategy", "legal", "code", "agents", "writing", "vision", "images", "video"]
CORE = (905, 200)
HIGHLIGHT = ("kimi", "legal")


def _chip(x: float, y: float, text: str, t: dict, anchor: str, hot: bool) -> str:
    w = 9 * len(text) + 22
    left = x - w if anchor == "end" else x
    stroke = t["accent"] if hot else t["chip_stroke"]
    color = t["accent"] if hot else t["ink"]
    return (f'<rect x="{left:.0f}" y="{y - 13:.0f}" width="{w}" height="26" rx="7" fill="{t["chip"]}" '
            f'stroke="{stroke}" stroke-width="{1.5 if hot else 1}"/>'
            f'<text x="{left + w / 2:.0f}" y="{y + 4.5:.0f}" font-family="{MONO}" font-size="13" fill="{color}" '
            f'text-anchor="middle">{text}</text>')


def _curve(x1: float, y1: float, x2: float, y2: float) -> str:
    mx = (x1 + x2) / 2
    return f"M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"


def render(theme: str) -> str:
    t = THEMES[theme]
    cx, cy = CORE
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'role="img" aria-label="Thalamus routes every job to the AI model built for it">',
             "<defs>",
             f'<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">'
             f'<circle cx="1" cy="1" r="1" fill="{t["muted"]}" opacity="0.18"/></pattern>',
             f'<radialGradient id="glow" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="{t["brain"]}" '
             f'stop-opacity="0.35"/><stop offset="1" stop-color="{t["brain"]}" stop-opacity="0"/></radialGradient>',
             f'<radialGradient id="core" cx="40%" cy="35%" r="70%"><stop offset="0" stop-color="{t["accent2"]}"/>'
             f'<stop offset="1" stop-color="{t["brain"]}"/></radialGradient>',
             "</defs>",
             f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>',
             f'<rect width="{W}" height="{H}" fill="url(#grid)"/>']

    # left: wordmark, pitch, command
    parts += [f'<text x="72" y="168" font-family="{SANS}" font-size="84" font-weight="800" fill="{t["ink"]}" '
              f'letter-spacing="-2.5">Thalamus</text>',
              f'<text x="76" y="214" font-family="{SANS}" font-size="25" fill="{t["ink"]}">'
              f'The right AI model for every job.</text>',
              f'<text x="76" y="248" font-family="{SANS}" font-size="19" fill="{t["muted"]}">'
              f'Re-ranked every Monday from open leaderboards.</text>',
              f'<rect x="72" y="282" width="452" height="42" rx="9" fill="{t["chip"]}" stroke="{t["chip_stroke"]}"/>',
              f'<text x="92" y="309" font-family="{MONO}" font-size="15" fill="{t["muted"]}">$ '
              f'<tspan fill="{t["ink"]}">thalamus route "fix this flaky test"</tspan></text>']

    # right: glow behind the relay
    parts.append(f'<ellipse cx="{cx}" cy="{cy}" rx="190" ry="150" fill="url(#glow)"/>')

    in_x, out_x = 690, 1130
    in_ys = [42 + i * (316 / (len(INPUTS) - 1)) for i in range(len(INPUTS))]
    out_ys = [56 + i * (288 / (len(OUTPUTS) - 1)) for i in range(len(OUTPUTS))]
    hot_path = ""
    for name, y in zip(INPUTS, in_ys):
        hot = name == HIGHLIGHT[0]
        d = _curve(in_x + 4, y, cx - 24, cy)
        hot_path = hot_path or (d if hot else "")
        parts.append(f'<path d="{d}" fill="none" stroke="{t["accent"] if hot else t["line"]}" '
                     f'stroke-width="{2.2 if hot else 1.4}" stroke-linecap="round" opacity="{1 if hot else 0.9}"/>')
    out_hot = ""
    for name, y in zip(OUTPUTS, out_ys):
        hot = name == HIGHLIGHT[1]
        d = _curve(cx + 24, cy, out_x - 4, y)
        out_hot = out_hot or (d if hot else "")
        parts.append(f'<path d="{d}" fill="none" stroke="{t["accent"] if hot else t["line"]}" '
                     f'stroke-width="{2.2 if hot else 1.4}" stroke-linecap="round" opacity="{1 if hot else 0.9}"/>')

    # the relay
    parts += [f'<circle cx="{cx}" cy="{cy}" r="46" fill="none" stroke="{t["brain"]}" stroke-opacity="0.35"/>',
              f'<circle cx="{cx}" cy="{cy}" r="34" fill="none" stroke="{t["brain"]}" stroke-opacity="0.55"/>',
              f'<circle cx="{cx}" cy="{cy}" r="22" fill="url(#core)"/>',
              f'<circle cx="{cx}" cy="{cy}" r="6" fill="{t["bg"]}" opacity="0.9"/>']

    # a signal travelling the highlighted route (a bonus; the static frame stands on its own)
    full = hot_path + " " + out_hot.replace("M", "L", 1)
    parts.append(f'<circle r="4.5" fill="{t["accent"]}"><animateMotion dur="3.6s" repeatCount="indefinite" '
                 f'path="{full}"/></circle>')

    for name, y in zip(INPUTS, in_ys):
        parts.append(_chip(in_x, y, name, t, "end", name == HIGHLIGHT[0]))
    for name, y in zip(OUTPUTS, out_ys):
        parts.append(_chip(out_x, y, name, t, "start", name == HIGHLIGHT[1]))
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)
    for theme in THEMES:
        (out / f"hero-{theme}.svg").write_text(render(theme) + "\n", encoding="utf-8")
        print(out / f"hero-{theme}.svg")


if __name__ == "__main__":
    main()
