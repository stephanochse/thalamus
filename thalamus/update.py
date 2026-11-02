"""The weekly sync: fetch every source, merge, score, write data/ and the generated docs.

    python -m thalamus update            # all sources
    python -m thalamus update --only aa,openrouter
    python -m thalamus update --offline  # rebuild from data/cache only

A source that fails keeps last week's cached copy, and the run report says so. Nothing is
silently dropped: data/sources.json lists every source with its row count or its error.
"""
from __future__ import annotations

import importlib
import json
import time
from datetime import datetime, timezone

from . import render
from .merge import merge
from . import paths
from .paths import DATA
from .score import build_routes, load_jobs

SOURCES = ["openrouter", "arena", "llmstats", "epoch"]
# Off by default because of their data terms (see each module). Turn on for a personal build with
# `thalamus update --personal --with aa,epoch_external` or config "extra_sources". A personal build writes to
# ~/.thalamus/data and never touches the repo, so nothing from these sources gets published.
OPTIONAL = ["aa", "epoch_external", "benchlm", "eqbench"]
# Never added: sites whose terms forbid automated access (Artificial Analysis pages, the Arena website,
# OpenRouter rankings pages, the Kilo leaderboard). Their APIs or open datasets are used instead.
CACHE = DATA / "cache"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_all(only: list[str] | None = None, offline: bool = False,
              extra: list[str] | None = None, cache_dir=None) -> tuple[dict, dict]:
    raw, status = {}, {}
    cache_dir = cache_dir or CACHE
    for name in SOURCES + [e for e in (extra or []) if e in OPTIONAL]:
        try:
            mod = importlib.import_module(f"thalamus.sources.{name}")
        except ModuleNotFoundError:
            continue
        if hasattr(mod, "CACHE_DIR"):
            mod.CACHE_DIR = cache_dir  # sources that cache per board (Arena) keep their pieces here
        cache = cache_dir / f"{name}.json"
        info = {"name": getattr(mod, "NAME", name), "url": getattr(mod, "URL", ""),
                "attribution": getattr(mod, "ATTRIBUTION", "")}
        fresh = not offline and (not only or name in only)
        if fresh:
            started = time.time()
            try:
                recs = mod.fetch()
                if not recs:
                    raise RuntimeError("source returned 0 rows")
                _write(cache, {"fetched": _today(), "records": recs})
                raw[name] = recs
                status[name] = {**info, "ok": True, "rows": len(recs), "fetched": _today(),
                                "seconds": round(time.time() - started, 1)}
                if getattr(mod, "PARTIAL", None):
                    status[name]["partial"] = list(mod.PARTIAL)  # boards that fell back to a cached copy
                continue
            except Exception as exc:  # one broken source must not stop the run
                info["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        if cache.exists():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            raw[name] = cached["records"]
            status[name] = {**info, "ok": not fresh, "rows": len(cached["records"]), "fetched": cached["fetched"],
                            "stale": fresh}

        else:
            status[name] = {**info, "ok": False, "rows": 0}
    return raw, status


def _extras(extra: list[str] | None) -> list[str]:
    if extra is not None:
        return extra
    try:
        from .paths import CONFIG
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("extra_sources", [])
    except (OSError, json.JSONDecodeError):
        return []


def _publishable(catalog: list[dict]) -> list[dict]:
    """Drop raw numbers from sources that don't allow redistribution. Job scores built from them stay."""
    closed = []
    for name in SOURCES + OPTIONAL:
        try:
            mod = importlib.import_module(f"thalamus.sources.{name}")
        except ModuleNotFoundError:
            continue
        if not getattr(mod, "REDISTRIBUTE", True):
            closed.append(getattr(mod, "PREFIX", name + "."))
    out = []
    for m in catalog:
        metrics = {k: v for k, v in m["metrics"].items() if not k.startswith(tuple(closed))}
        clean = {**m, "metrics": metrics}
        if "aa." in closed:
            clean.pop("speed", None)
            clean["metrics"] = {k: v for k, v in metrics.items() if k not in ("x.tps", "x.ttft")}
        out.append(clean)
    return out


def _closed_prefixes() -> tuple[str, ...]:
    out = []
    for name in SOURCES + OPTIONAL:
        try:
            mod = importlib.import_module(f"thalamus.sources.{name}")
        except ModuleNotFoundError:
            continue
        if not getattr(mod, "REDISTRIBUTE", True):
            out.append(getattr(mod, "PREFIX", name + "."))
    return tuple(out)


def _publishable_routes(routes: dict) -> dict:
    """Speed only comes from Artificial Analysis, whose raw numbers aren't redistributed: the fast picks
    still use it, but the published rows don't carry the figure."""
    if "aa." not in _closed_prefixes():
        return routes
    out = {}
    for job_id, e in routes.items():
        e = dict(e)
        e["top"] = [{k: v for k, v in r.items() if k != "tps"} for r in e.get("top", [])]
        e["picks"] = {role: {k: v for k, v in r.items() if k != "tps"} for role, r in e.get("picks", {}).items()}
        out[job_id] = e
    return out


def run(only: list[str] | None = None, offline: bool = False, quiet: bool = False,
        extra: list[str] | None = None, personal: bool = False) -> dict:
    """personal=True writes to ~/.thalamus/data (with opt-in sources) and leaves the repo alone."""
    out_dir = paths.PERSONAL_DATA if personal else DATA
    extras = _extras(extra) if personal else []
    if not personal and extra:
        raise SystemExit("Opt-in sources don't allow public redistribution: add --personal to use "
                         f"{', '.join(extra)} (writes to ~/.thalamus/data, never the repo).")
    raw, status = fetch_all(only, offline, extras, cache_dir=out_dir / "cache")
    if not raw.get("openrouter"):
        raise RuntimeError("OpenRouter catalog unavailable and no cache: nothing to merge onto.")
    catalog, unmatched = merge(raw)
    jobs = load_jobs()
    routes = build_routes(catalog, jobs)
    previous = {}
    prev_path = out_dir / "routes.json"
    if prev_path.exists():
        try:
            previous = json.loads(prev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    updated = _today()
    payload = {"updated": updated, "sources": status, "personal": personal,
               "jobs": routes if personal else _publishable_routes(routes)}
    scored = [m for m in catalog if not m.get("catalog_only")]
    _write(out_dir / "models.json", {"updated": updated, "count": len(catalog), "scored": len(scored),
                                  "models": sorted(catalog if personal else _publishable(catalog), key=lambda m: m["id"])})
    _write(prev_path, payload)
    _write(out_dir / "sources.json", {"updated": updated, "sources": status})
    _write(out_dir / "unmatched.json", {"updated": updated, "note": "Add an entry to data/aliases.json to merge these.",
                                     "records": unmatched})
    changes = render.diff(previous, payload, catalog, out_dir)
    if personal:
        (out_dir / "ROUTES.md").write_text(render.routes_md(payload, jobs), encoding="utf-8")
    else:
        render.write_all(payload, catalog, changes, jobs)
    _write(out_dir / "last_run.json", {"ran": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "sources_ok": sum(1 for s in status.values() if s.get("ok")),
                                    "sources_total": len(status), "models": len(catalog), "scored": len(scored)})
    summary = {"updated": updated, "models": len(catalog), "scored": len(scored), "unmatched": len(unmatched),
               "sources": {k: ("ok" if v.get("ok") else ("STALE" if v.get("stale") else "FAIL")) + f" {v.get('rows', 0)}"
                           for k, v in status.items()},
               "changes": changes.get("headline", [])}
    if not quiet:
        print(json.dumps(summary, indent=1))
    return summary
