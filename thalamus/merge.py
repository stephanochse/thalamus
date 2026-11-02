"""Fuse records from every source into one catalog: one entry per model (and reasoning variant).

Matching order for each record:
  1. data/aliases.json   exact override  {"aa:gpt-6-high": "openai/gpt-6"}
  2. slug_hint           the source already knows the OpenRouter id
  3. same lab + same canonical name           "GPT-6.1 Terra (high)" -> "gpt-6.1-terra"
  4. same lab + same set of name tokens       "Claude 5 Sonnet" == "Claude Sonnet 5"
Anything still unmatched becomes its own entry (id "<source>:<key>") and is listed in
data/unmatched.json, so a human or an agent can add an alias next week.
"""
from __future__ import annotations

import json
import re

from .paths import DATA

LABS = {
    "openai": ("OpenAI", "US"), "anthropic": ("Anthropic", "US"), "google": ("Google", "US"),
    "xai": ("xAI", "US"), "meta": ("Meta", "US"), "amazon": ("Amazon", "US"), "microsoft": ("Microsoft", "US"),
    "nvidia": ("NVIDIA", "US"), "ibm": ("IBM", "US"), "perplexity": ("Perplexity", "US"), "inception": ("Inception", "US"),
    "liquid": ("Liquid AI", "US"), "reka": ("Reka", "US"), "arcee": ("Arcee", "US"), "allenai": ("Ai2", "US"),
    "zhipu": ("Zhipu (Z.ai)", "CN"), "moonshot": ("Moonshot AI", "CN"), "alibaba": ("Alibaba (Qwen)", "CN"),
    "deepseek": ("DeepSeek", "CN"), "minimax": ("MiniMax", "CN"), "baidu": ("Baidu", "CN"), "tencent": ("Tencent", "CN"),
    "bytedance": ("ByteDance", "CN"), "stepfun": ("StepFun", "CN"), "xiaomi": ("Xiaomi", "CN"), "meituan": ("Meituan", "CN"),
    "kuaishou": ("Kuaishou (Kling)", "CN"), "shengshu": ("Shengshu (Vidu)", "CN"), "hailuo": ("MiniMax (Hailuo)", "CN"),
    "mistral": ("Mistral", "FR"), "cohere": ("Cohere", "CA"), "ai21": ("AI21", "IL"), "bfl": ("Black Forest Labs", "DE"),
    "stability": ("Stability AI", "UK"), "elevenlabs": ("ElevenLabs", "US"), "ideogram": ("Ideogram", "US"),
    "midjourney": ("Midjourney", "US"), "runway": ("Runway", "US"), "luma": ("Luma", "US"), "recraft": ("Recraft", "US"),
    "upstage": ("Upstage", "KR"), "lg": ("LG AI Research", "KR"), "sakana": ("Sakana AI", "JP"), "tii": ("TII", "AE"),
    "sarvam": ("Sarvam", "IN"), "nous": ("Nous Research", "US"),
}
LAB_ALIASES = {
    "z.ai": "zhipu", "z-ai": "zhipu", "zai": "zhipu", "zhipu ai": "zhipu", "z ai": "zhipu", "thudm": "zhipu",
    "moonshotai": "moonshot", "moonshot ai": "moonshot", "kimi": "moonshot",
    "x-ai": "xai", "spacexai": "xai", "spacex ai": "xai", "x.ai": "xai",
    "meta-llama": "meta", "meta ai": "meta", "facebook": "meta",
    "mistralai": "mistral", "mistral ai": "mistral", "qwen": "alibaba", "alibaba cloud": "alibaba",
    "google deepmind": "google", "deepmind": "google", "gemini": "google",
    "deepseek-ai": "deepseek", "minimaxai": "minimax", "bytedance seed": "bytedance", "bytedance-seed": "bytedance",
    "black forest labs": "bfl", "black-forest-labs": "bfl", "stability ai": "stability", "stabilityai": "stability",
    "amazon nova": "amazon", "aws": "amazon", "kling": "kuaishou", "kling ai": "kuaishou", "vidu": "shengshu",
    "nvidia nemotron": "nvidia", "ai2": "allenai", "allen ai": "allenai", "nousresearch": "nous", "ibm-granite": "ibm",
    "liquid ai": "liquid", "liquidai": "liquid", "inception labs": "inception", "openai": "openai",
}
SUBSCRIPTION_CLI = {"openai": "codex", "anthropic": "claude-cli", "xai": "grok", "google": "agy"}
NOISE = r"\b(preview|latest|exp|experimental|instruct|chat|it|hf|online|beta|new)\b"
EFFORT_WORDS = {"minimal", "low", "medium", "high", "xhigh", "max", "thinking", "reasoning", "nothinking",
                "search", "fast"}
VARIANT = r"\(([^)]*)\)"


LAB_SUFFIXES = r"\b(ai|research|cloud|team|inc|labs?|llc|ltd|technologies|technology|corp)\b"


def _lab_candidates(label: str) -> list[str]:
    raw = label.strip().lower()
    inner = re.findall(r"\(([^)]*)\)", raw)                    # "z.ai (zhipu ai)" -> also try "zhipu ai"
    head = re.split(r"[,/(]", raw)[0].strip()                  # "alibaba cloud / qwen team" -> "alibaba cloud"
    parts = [raw, head] + inner + [p.strip() for p in re.split(r"[,/]", raw)]
    out = []
    for p in parts:
        for cand in (p, re.sub(LAB_SUFFIXES, "", p).strip()):
            if cand and cand not in out:
                out.append(cand)
    return out


def lab_id(label: str | None) -> str | None:
    if not label:
        return None
    for cand in _lab_candidates(label):
        key = LAB_ALIASES.get(cand, cand)
        if key in LABS:
            return key
        squashed = re.sub(r"[^a-z0-9]", "", key)
        squashed = LAB_ALIASES.get(squashed, squashed)
        if squashed in LABS:
            return squashed
    return re.sub(r"[^a-z0-9]", "", label.lower()) or None


def _strip_effort(s: str) -> tuple[str, str | None]:
    """'claude-opus-5-high' -> ('claude-opus-5', 'high'). Names without a trailing effort word pass through."""
    if " " in s.strip():  # only slug-style names ("claude-opus-5-high") carry effort as a suffix
        return s, None
    parts = [p for p in re.split(r"[-_]+", s.strip()) if p]
    if len(parts) > 2 and parts[-1] in EFFORT_WORDS - {"max"}:  # "max" is also a model tier (Qwen Max)
        return "-".join(parts[:-1]), parts[-1]
    return s, None


def canon(name: str) -> str:
    s = name.lower()
    s = re.sub(VARIANT, " ", s)
    s = _strip_effort(s)[0]
    s = re.sub(r"^[a-z0-9.\- ]+:\s*", "", s) if ":" in s else s  # drop "OpenAI: " prefixes
    s = re.sub(NOISE, " ", s)
    s = re.sub(r"\b20\d\d[-_]?\d\d[-_]?\d\d\b|\b\d{4}\b(?=\s*$)", " ", s)
    s = re.sub(r"([a-z])(\d)", r"\1-\2", s)  # "qwen3.8" and "qwen 3.8" become the same name
    s = re.sub(r"[^a-z0-9.]+", "-", s).strip("-.")
    return s


def tokens(name: str) -> frozenset:
    return frozenset(t for t in re.split(r"-", canon(name)) if t)


def variant_of(name: str) -> str | None:
    found = re.findall(VARIANT, name)
    if not found:
        return _strip_effort(name.lower())[1]
    v = found[-1].split(",")[0].strip().lower()  # "(Max, Default Fallback)" -> "max"
    first = v.split()[0] if v.split() else ""
    # only effort levels are variants; dates, quantization and "(Preview)" are not
    return first if first in EFFORT_WORDS else None


def clean_name(name: str) -> str:
    """Keep "(High)" style effort tags, drop "(Preview)", "(1203)", "(unknown thinking)" and similar noise."""
    def keep(m: re.Match) -> str:
        first = m.group(1).split(",")[0].strip().lower().split()
        return m.group(0) if first and first[0] in EFFORT_WORDS else ""
    return re.sub(r"\s+", " ", re.sub(VARIANT, keep, name)).strip()


def _load_aliases() -> dict:
    path = DATA / "aliases.json"
    try:
        return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    except (OSError, json.JSONDecodeError):
        return {}


def _new_entry(rec: dict, base: str, variant: str | None) -> dict:
    lid = lab_id(rec.get("lab"))
    lab_name, country = LABS.get(lid, (rec.get("lab"), None))
    return {
        "id": f"{base}@{variant}" if variant else base, "base": base, "name": rec["name"], "variant": variant,
        "lab": lab_name, "lab_id": lid, "country": country, "kind": rec.get("kind", "llm"),
        "open_weights": rec.get("open_weights"), "released": rec.get("released"), "context": rec.get("context"),
        "input": rec.get("input"), "reasoning": rec.get("reasoning"), "price": rec.get("price"),
        "speed": rec.get("speed"), "metrics": {}, "where": {}, "sources": [],
    }


def _absorb(entry: dict, rec: dict) -> None:
    for k, v in rec.get("metrics", {}).items():
        entry["metrics"].setdefault(k, v)
    entry["where"].setdefault(rec["source"], rec["key"])
    if rec["source"] not in entry["sources"]:
        entry["sources"].append(rec["source"])
    if rec.get("unreleased"):
        entry["unreleased"] = True
    for field in ("context", "input", "released", "reasoning", "speed"):
        if not entry.get(field) and rec.get(field):
            entry[field] = rec[field]
    if entry.get("open_weights") is None and rec.get("open_weights") is not None:
        entry["open_weights"] = rec["open_weights"]
    if not entry.get("price") and rec.get("price"):
        entry["price"] = rec["price"]
    if rec["source"] == "openrouter" and rec.get("price"):
        entry["price"] = rec["price"]  # the callable price wins
    if rec.get("lab") and not entry.get("lab"):
        entry["lab"] = rec["lab"]


def merge(raw: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    aliases = _load_aliases()
    catalog: dict[str, dict] = {}
    by_canon: dict[tuple, str] = {}
    by_tokens: dict[tuple, str] = {}
    by_canon_any: dict[tuple, list[str]] = {}

    # 1) backbone: every callable OpenRouter model
    for rec in raw.get("openrouter", []):
        e = _new_entry(rec, rec["key"], None)
        _absorb(e, rec)
        e["where"]["openrouter"] = rec["key"]
        catalog[e["id"]] = e
        slug_name = rec["key"].split("/", 1)[-1]
        for nm in (rec["name"], slug_name):
            by_canon[(e["kind"], e["lab_id"], canon(nm))] = e["id"]
            by_tokens[(e["kind"], e["lab_id"], tokens(nm))] = e["id"]
            by_canon_any.setdefault((e["kind"], canon(nm)), []).append(e["id"])

    unmatched = []
    for source, recs in raw.items():
        if source == "openrouter":
            continue
        for rec in recs:
            kind = rec.get("kind", "llm")
            lid = lab_id(rec.get("lab"))
            variant = rec.get("variant") or variant_of(rec["name"])
            target = aliases.get(f"{source}:{rec['key']}")
            if not target and rec.get("slug_hint") in catalog:
                target = rec["slug_hint"]
            if not target:
                target = by_canon.get((kind, lid, canon(rec["name"]))) or by_tokens.get((kind, lid, tokens(rec["name"])))
            if not target:
                hits = by_canon_any.get((kind, canon(rec["name"])), [])
                target = hits[0] if len(hits) == 1 else None
            if target and target in catalog:
                base_entry = catalog[catalog[target]["base"]] if catalog[target]["base"] in catalog else catalog[target]
                if variant and rec.get("metrics"):
                    vid = f"{base_entry['base']}@{variant}"
                    if vid not in catalog:
                        ve = _new_entry({**rec, "lab": base_entry.get("lab")}, base_entry["base"], variant)
                        ve["name"] = clean_name(rec["name"])
                        for f in ("price", "context", "input", "open_weights", "released", "reasoning", "lab_id",
                                  "lab", "country"):
                            ve[f] = base_entry.get(f) if base_entry.get(f) is not None else ve.get(f)
                        ve["where"] = dict(base_entry["where"])
                        catalog[vid] = ve
                    _absorb(catalog[vid], rec)
                else:
                    _absorb(base_entry, rec)
                continue
            # unmatched: a neutral base entry for the model, keyed by source, plus a separate entry per effort
            # variant, so "(High)" scores never land on "(Low)"
            key_tuple = (kind, lid, canon(rec["name"]))
            base_id = by_canon.get(key_tuple) or by_tokens.get((kind, lid, tokens(rec["name"])))
            if not base_id or base_id not in catalog:
                base_id = f"{source}:{canon(rec['name']) or rec['key']}"
                base = _new_entry({**rec, "price": rec.get("price")}, base_id, None)
                base["name"] = re.sub(VARIANT, "", rec["name"]).strip()
                catalog[base_id] = base
                by_canon[key_tuple] = base_id
                by_tokens[(kind, lid, tokens(rec["name"]))] = base_id
                by_canon_any.setdefault((kind, canon(rec["name"])), []).append(base_id)
                if kind == "llm":
                    unmatched.append({"source": source, "source_id": rec["key"], "name": rec["name"],
                                      "lab": rec.get("lab")})
            base = catalog[base_id]
            if variant and rec.get("metrics"):
                vid = f"{base_id}@{variant}"
                if vid not in catalog:
                    ve = _new_entry(rec, base_id, variant)
                    ve["name"] = clean_name(rec["name"])
                    ve["where"] = dict(base["where"])
                    catalog[vid] = ve
                _absorb(catalog[vid], rec)
            else:
                _absorb(base, rec)

    # 2) variants inherit the base model's non-variant signals (arena, usage) they don't have yet
    for e in catalog.values():
        if e["variant"] and e["base"] in catalog:
            for k, v in catalog[e["base"]]["metrics"].items():
                if not k.startswith("aa."):
                    e["metrics"].setdefault(k, v)

    # 3) derived fields
    out = []
    for e in catalog.values():
        if e.get("context"):
            e["metrics"]["x.context"] = e["context"]
        p = e.get("price") or {}
        if p.get("blended") is not None and e["kind"] == "llm":
            e["metrics"]["x.price"] = p["blended"]
        sp = e.get("speed") or {}
        if sp.get("tps"):
            e["metrics"]["x.tps"] = sp["tps"]
        if sp.get("ttft"):
            e["metrics"]["x.ttft"] = sp["ttft"]
        access = []
        if e["where"].get("openrouter"):
            # models not on a public API (previews, retired, limited rollouts) get no access, so they show in
            # tables but are never picked. Which models YOUR subscription CLIs serve is personal config
            # ("served" in ~/.thalamus/config.json), applied when routing, never guessed from the lab.
            access.append("openrouter")
        e["access"] = access
        if e["sources"] == ["openrouter"] and not e["metrics"].keys() - {"x.context", "x.price"}:
            e["catalog_only"] = True  # callable, but no source has scored it yet
        out.append(e)
    return out, unmatched
