"""Text from third-party feeds and issues is untrusted. Model and lab names end up in markdown tables, agent
rule files, SVG and JSON that AI agents read, so they're cleaned once on the way in (clean_text) and escaped
again on the way out (md)."""
from __future__ import annotations

import re

# letters and digits in any script, plus the punctuation real model names use
_UNSAFE = re.compile(r"[^\w .,:+()/@'&%-]")


def clean_text(value, limit: int = 80) -> str | None:
    """Printable, single-line, no markup characters, at most `limit` characters."""
    if value is None:
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    text = re.sub(r"\s+", " ", _UNSAFE.sub("", text)).strip()
    return text[:limit].strip() or None


def md(value) -> str:
    """Safe inside a markdown table cell, a code span or a code block."""
    text = re.sub(r"\s+", " ", str(value if value is not None else ""))
    for bad, good in (("|", "/"), ("`", "'"), ("<", ""), (">", ""), ("[", "("), ("]", ")")):
        text = text.replace(bad, good)
    return text.strip()
