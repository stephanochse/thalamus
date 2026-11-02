"""Privacy filter for anything that leaves the machine through a council seat.

Always removes secret-shaped strings (API keys, tokens, JWTs), email addresses and phone numbers.
Also removes every term listed in HOME/private-terms.txt (one per line, case-insensitive, whole word),
replacing each with a stable placeholder like [TERM-2]. After replacing, it checks again and refuses to
proceed if any listed term is still present (a case-sensitive swap once missed capitals; only a re-check
caught it).

It cannot catch paraphrases. Keep the brief minimal as well.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{16,}",                       # OpenAI, Anthropic (sk-ant-), OpenRouter (sk-or-)
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}",  # payment-provider style keys
    r"gh[pousr]_[A-Za-z0-9]{20,}",                   # GitHub tokens
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"xox[abprs]-[A-Za-z0-9-]{10,}",                 # Slack
    r"AKIA[0-9A-Z]{16}",                             # AWS access key id
    r"AIza[0-9A-Za-z_\-]{30,}",                      # Google API key
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWT
    r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
]
# key = value pairs where the value looks like a long secret: keep the key, drop the value.
KEYED_SECRET = re.compile(
    r"(?i)\b((?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|password|passwd|pwd)\b[\"']?\s*[:=]\s*[\"']?)"
    r"([A-Za-z0-9_\-+/=.]{16,})")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?|\d{2,4}[\s.\-])\d{2,4}[\s.\-]\d{2,4}(?:[\s.\-]\d{2,4})?(?!\w)")


@dataclass
class ScrubResult:
    text: str
    counts: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)  # placeholder -> original term; for the host only, never sent out

    def summary(self) -> str:
        parts = [f"{n} {kind}" for kind, n in self.counts.items() if n]
        return ", ".join(parts) if parts else "nothing"


def terms_file() -> Path:
    return paths.HOME / "private-terms.txt"


def load_terms(path: Path | None = None) -> list[str]:
    path = path or terms_file()
    if not path.exists():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return sorted(set(terms), key=str.lower)


def _term_regex(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.IGNORECASE)


def _is_phone(match: re.Match) -> bool:
    """Digit-count and date guards keep dates, versions and short ids out of the phone bucket."""
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 15:
        return False
    if re.fullmatch(r"\d{4}[\-./]\d{1,2}[\-./]\d{1,2}", raw) or re.fullmatch(r"\d{1,2}[\-./]\d{1,2}[\-./]\d{2,4}", raw):
        return False
    return True


def scrub(text: str, keep_emails: bool = False, extra_terms: list[str] | None = None) -> ScrubResult:
    counts = {"secrets": 0, "emails": 0, "phones": 0, "names": 0}
    out = text
    for pat in SECRET_PATTERNS:
        out, n = re.subn(pat, "[secret]", out)
        counts["secrets"] += n
    out, n = KEYED_SECRET.subn(lambda m: m.group(1) + "[secret]", out)
    counts["secrets"] += n
    if not keep_emails:
        out, n = EMAIL.subn("[email]", out)
        counts["emails"] += n

    hits = 0

    def phone_sub(m: re.Match) -> str:
        nonlocal hits
        if _is_phone(m):
            hits += 1
            return "[phone]"
        return m.group(0)

    out = PHONE.sub(phone_sub, out)
    counts["phones"] = hits

    terms = sorted(set(load_terms() + list(extra_terms or [])), key=str.lower)
    numbering = {t: i for i, t in enumerate(terms, start=1)}
    names: dict[str, str] = {}
    for term in sorted(terms, key=len, reverse=True):  # longest first: "Acme Corp" before "Acme"
        placeholder = f"[TERM-{numbering[term]}]"
        out, n = _term_regex(term).subn(placeholder, out)
        if n:
            names[placeholder] = term
            counts["names"] += n
    leftovers = [t for t in terms if _term_regex(t).search(out)]
    if leftovers:
        raise ValueError(f"Privacy check failed, not sending: {len(leftovers)} private term(s) still present")
    return ScrubResult(out, counts, names)
