"""The brain: what Thalamus learns about itself every week.

Leaderboards change every week, and sometimes a feed breaks or a parser starts reading the wrong
column. Before the weekly sync trusts its inputs, the brain checks them against each other and
against last week, keeps a memory of past weeks, and writes down what it learned in BRAIN.md.

  quarantine        a metric whose rankings reshuffle overnight (rank correlation with last week
                    under QUARANTINE_RHO) or that lost most of its rows sits out this week
  source_agreement  per source: how well its view of each job agrees with every other source
  update_trust      a sudden drop in that agreement, against the source's own baseline, lowers its
                    weight (halfway each week, never under TRUST_MIN); steady sources keep full weight
  apply_trust       scales each job's metric weights by its source's trust
  apply_community   verdicts filed by users as GitHub issues nudge scores by at most 10%
  steady            a new #1 has to beat last week's by more than STEADY_MARGIN points
  remember, movers  26 weeks of top lists per job: who is rising and who is falling
  lab_champions     the best model from every lab for a job, and how close it gets to the top
  rival             the best model from another lab: the second opinion that thinks differently
  reflect           BRAIN.md: what changed, what it trusts less, what it can't judge yet

Every function returns new objects and leaves its inputs alone.
"""
from __future__ import annotations

import math
from statistics import mean

from . import score
from .safe import md

QUARANTINE_RHO = 0.5      # rank correlation with last week below this = the feed probably broke
LOST_SHARE = 0.5          # keeping less than half of last week's rows = the feed probably broke
TRUST_MIN, TRUST_MAX = 0.5, 1.0
TRUST_STEP = 0.5          # move halfway toward this week's target, so one odd week can't swing it
DROP_ALLOWED = 0.2        # agreement may dip this far below the source's own baseline without penalty
DROP_PENALTY = 1.5        # trust lost per point of agreement below that
BASELINE_STEP = 0.3       # how fast a source's normal level of agreement follows the data
FLAGGED_WEEKS = 3         # after this many low weeks in a row, the lower agreement becomes the baseline
STEADY_MARGIN = 1.0       # score points a challenger needs over last week's best pick
RIVAL_BAND = 0.80         # a rival must reach 80% of the best pick's quality
HISTORY_WEEKS = 26
HISTORY_DEPTH = 15
PREFIX_SOURCE = {"epochx": "epoch_external"}


# ---------------------------------------------------------------- statistics

def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(a) != len(b):
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = mean(ra), mean(rb)
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / math.sqrt(va * vb)


def metric_source(metric_id: str) -> str | None:
    """'arena.coding' -> 'arena'. Derived fields (x.price, x.tps) belong to no source."""
    prefix = metric_id.split(".", 1)[0]
    if prefix == "x":
        return None
    return PREFIX_SOURCE.get(prefix, prefix)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


# ---------------------------------------------------------------- self-checks

def metric_map(models: list[dict]) -> dict[str, dict[str, float]]:
    """{model id: {metric: value}} for source metrics only, the snapshot quarantine compares against."""
    return {m["id"]: {k: v for k, v in (m.get("metrics") or {}).items() if metric_source(k) and _num(v)}
            for m in models}


def quarantine(previous: dict[str, dict], now: dict[str, dict], min_rows: int = 15,
               min_overlap: int = 10) -> dict[str, str]:
    """Metrics that look broken compared with last week, with the reason."""
    out = {}
    names = sorted({k for vals in previous.values() for k in vals})
    for metric in names:
        before = {m: v[metric] for m, v in previous.items() if metric in v}
        if len(before) < min_rows:
            continue
        after = {m: v[metric] for m, v in now.items() if metric in v}
        if len(after) < LOST_SHARE * len(before):
            out[metric] = f"lost {len(before) - len(after)} of {len(before)} rows since last week"
            continue
        common = sorted(set(before) & set(after))
        if len(common) >= min_overlap:
            rho = spearman([before[c] for c in common], [after[c] for c in common])
            if rho is not None and rho < QUARANTINE_RHO:
                out[metric] = f"rankings reshuffled overnight (rank correlation {rho:.2f} with last week)"
    return out


def carry_forward(now: dict[str, dict], base: dict[str, dict], quarantined: dict) -> dict[str, dict]:
    """This week's values, except quarantined metrics keep last week's, so a feed that stays broken is still
    caught next week and a fixed one isn't flagged for changing back."""
    out = {}
    for model, vals in now.items():
        kept = {k: v for k, v in vals.items() if k not in quarantined}
        kept.update({k: v for k, v in (base.get(model) or {}).items() if k in quarantined})
        out[model] = kept
    return out


def _scaled_job(job: dict, pool: list[dict]) -> dict[str, dict[str, float]]:
    out = {}
    for mt in job["metrics"]:
        if not metric_source(mt["id"]):
            continue
        vals = {m["id"]: float(m["metrics"][mt["id"]]) for m in pool if _num((m.get("metrics") or {}).get(mt["id"]))}
        out[mt["id"]] = score._scale(vals, mt.get("higher", True))
    return out


def _blend(model_id: str, metrics: list[dict], scaled: dict) -> float | None:
    got = [(mt["w"], scaled[mt["id"]][model_id]) for mt in metrics if model_id in scaled.get(mt["id"], {})]
    w = sum(g[0] for g in got)
    return sum(a * b for a, b in got) / w if w else None


def source_agreement(models: list[dict], jobs: list[dict], min_models: int = 8) -> dict[str, float]:
    """Leave-one-out agreement: for every job, rank models by one source alone and by all the others,
    and correlate the two. Averaged over jobs, weighted by how many models were compared. A source that
    measures something different still agrees partly; a broken one drops toward zero."""
    acc: dict[str, list[float]] = {}
    for job in jobs:
        pool = [m for m in models if score._eligible(m, job)]
        scaled = _scaled_job(job, pool)
        metrics = [mt for mt in job["metrics"] if mt["id"] in scaled and scaled[mt["id"]]]
        sources = sorted({metric_source(mt["id"]) for mt in metrics})
        if len(sources) < 2:
            continue
        for src in sources:
            mine = [mt for mt in metrics if metric_source(mt["id"]) == src]
            others = [mt for mt in metrics if metric_source(mt["id"]) != src]
            pairs = [(a, b) for m in pool
                     if (a := _blend(m["id"], mine, scaled)) is not None and (b := _blend(m["id"], others, scaled)) is not None]
            if len(pairs) < min_models:
                continue
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if rho is None:
                continue
            total = acc.setdefault(src, [0.0, 0.0])
            total[0] += rho * len(pairs)
            total[1] += len(pairs)
    return {src: round(s / n, 3) for src, (s, n) in acc.items() if n}


def trust_target(agreement: float, baseline: float | None) -> float:
    """Full trust while a source agrees with the others about as much as it usually does. Sources measure
    different things (a hallucination board barely correlates with a human-preference board), so the level
    of agreement says little; a sudden drop below the source's own baseline is what a broken feed looks like."""
    if baseline is None:
        return 1.0
    drop = baseline - agreement
    if drop <= DROP_ALLOWED:
        return 1.0
    return max(TRUST_MIN, 1.0 - DROP_PENALTY * (drop - DROP_ALLOWED))


def update_trust(previous: dict, agreement: dict[str, float]) -> dict:
    out = {}
    for src in sorted(set(previous) | set(agreement)):
        prev = previous.get(src, {})
        old = prev.get("trust", 1.0)
        baseline = prev.get("baseline")
        if src not in agreement:
            out[src] = {**prev, "trust": old, "agreement": None, "note": "no overlap with other sources this week"}
            continue
        ag = agreement[src]
        target = trust_target(ag, baseline)
        new = min(TRUST_MAX, max(TRUST_MIN, old + TRUST_STEP * (target - old)))
        # a week that looks broken doesn't drag the baseline down with it, but a drop that lasts
        # FLAGGED_WEEKS weeks is the source's new normal, and the baseline follows
        flagged = prev.get("flagged", 0) + 1 if target < 1.0 else 0
        if baseline is None:
            new_baseline = ag
        elif 0 < flagged < FLAGGED_WEEKS:
            new_baseline = baseline
        else:
            new_baseline = baseline + BASELINE_STEP * (ag - baseline)
        out[src] = {"trust": round(new, 3), "agreement": ag, "baseline": round(new_baseline, 3),
                    "previous": round(old, 3), "weeks": prev.get("weeks", 0) + 1, "flagged": flagged}
    return out


def apply_trust(jobs: list[dict], trust: dict, quarantined: set | dict) -> list[dict]:
    out = []
    for job in jobs:
        metrics = []
        for mt in job["metrics"]:
            if mt["id"] in quarantined:
                continue
            src = metric_source(mt["id"])
            t = (trust.get(src) or {}).get("trust", 1.0) if src else 1.0
            metrics.append({**mt, "w": round(mt["w"] * t, 3)})
        out.append({**job, "metrics": metrics})
    return out


def apply_community(rows: list[dict], votes: dict[str, dict]) -> list[dict]:
    """Nudge scores by the community's verdicts for this job (at most +/-10%, only past 5 voters)."""
    if not votes:
        return rows
    from . import community
    out = []
    for r in rows:
        v = votes.get(r["id"]) or votes.get(r["id"].split("@", 1)[0])
        if not v:
            out.append(r)
            continue
        f = community.factor(v.get("good", 0), v.get("bad", 0), v.get("voters", 0))
        out.append({**r, "score": round(r["score"] * f, 1),
                    "community": f"{v.get('good', 0)} good / {v.get('bad', 0)} bad from {v.get('voters', 0)} people"})
    out.sort(key=lambda r: (-r["score"], r["price"] if r.get("price") is not None else 1e9))
    return [{**r, "rank": i} for i, r in enumerate(out, 1)]


# ---------------------------------------------------------------- picks

def _lab(row: dict) -> str:
    return row.get("lab") or row["id"].split("/", 1)[0]


def steady(picks: dict, rows: list[dict], previous_best: str | None, margin: float = STEADY_MARGIN) -> dict:
    """Keep last week's best pick when this week's #1 beats it by no more than `margin` points."""
    best = picks.get("best")
    if not best or not previous_best or best["id"] == previous_best:
        return picks
    incumbent = next((r for r in rows if r["id"] == previous_best and r.get("pickable", True)), None)
    if not incumbent or best["score"] - incumbent["score"] > margin:
        return picks
    return {**picks, "best": {**incumbent, "held": f"within {margin} of the top score, kept from last week"}}


def rival(rows: list[dict], best: dict | None) -> dict | None:
    if not best:
        return None
    floor = RIVAL_BAND * best.get("quality", best["score"])
    return next((r for r in rows if r.get("pickable", True) and _lab(r) != _lab(best)
                 and r.get("quality", r["score"]) >= floor), None)


def lab_champions(rows: list[dict]) -> list[dict]:
    """The best model you can call from each lab, best lab first. `rank` is its place in the full table,
    `place` its place among callable models, `of_best` its share of the top callable score."""
    ordered = sorted(rows, key=lambda r: -r["score"])
    callable_rows = [r for r in ordered if r.get("pickable", True)]
    if not callable_rows:
        return []
    top = callable_rows[0]["score"] or 1
    seen, out = set(), []
    for place, r in enumerate(callable_rows, 1):
        lab = _lab(r)
        if lab in seen:
            continue
        seen.add(lab)
        out.append({"lab": lab, "id": r["id"], "name": r["name"], "score": r["score"],
                    "rank": r.get("rank", ordered.index(r) + 1), "place": place,
                    "of_best": round(100 * r["score"] / top), "price": r.get("price"),
                    "price_unit": r.get("price_unit")})
    return out


# ---------------------------------------------------------------- memory

def _dedupe_ids(rows: list[dict], keep: int) -> list[list]:
    seen, out = set(), []
    for r in rows:
        base = r["id"].split("@", 1)[0]
        if base in seen:
            continue
        seen.add(base)
        out.append([r["id"], r["score"], r.get("name", r["id"])])
        if len(out) == keep:
            break
    return out


def _iso_week(date: str) -> str:
    from datetime import date as _date
    try:
        y, w, _ = _date.fromisoformat(date[:10]).isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return date


def remember(history: dict, date: str, jobs: dict) -> dict:
    """One entry per ISO week: a re-run in the same week replaces that week's entry."""
    week = {"date": date, "jobs": {j: _dedupe_ids(e.get("top", []), HISTORY_DEPTH) for j, e in jobs.items()}}
    weeks = [w for w in (history or {}).get("weeks", []) if _iso_week(w.get("date", "")) != _iso_week(date)] + [week]
    weeks.sort(key=lambda w: w["date"])
    return {"weeks": weeks[-HISTORY_WEEKS:]}


def movers(history: dict, job: str) -> list[dict]:
    """Rank changes between the last two weeks for one job; risers first, then new arrivals."""
    weeks = (history or {}).get("weeks", [])
    if len(weeks) < 2:
        return []
    now = weeks[-1]["jobs"].get(job, [])
    # compared by base model, so a model whose best effort level changes isn't a "new" arrival
    was = {row[0].split("@", 1)[0]: i for i, row in enumerate(weeks[-2]["jobs"].get(job, []), 1)}
    if not was:
        return []
    moved, new = [], []
    for i, (full_id, sc, name) in enumerate(now, 1):
        mid = full_id.split("@", 1)[0]
        if mid not in was:
            new.append({"id": mid, "name": name, "now": i, "was": None, "moved": None, "new": True})
        elif was[mid] != i:
            moved.append({"id": mid, "name": name, "now": i, "was": was[mid], "moved": was[mid] - i})
    moved.sort(key=lambda m: (-abs(m["moved"]), -m["moved"]))
    return moved + new


# ---------------------------------------------------------------- reflection

def _thin(jobs: dict, limit: int = 12) -> list[str]:
    """Strong text models ranked on far less evidence than their peers for the same job (usually because
    they're new): the ones the brain can't judge well yet. Image and video jobs rest on one arena board by
    design, so they're left out."""
    out = []
    for j, e in jobs.items():
        if "llm" not in e.get("kinds", ["llm"]):
            continue
        top = e.get("top", [])[:15]
        if not top:
            continue
        typical = sorted(r.get("coverage", 1.0) for r in top)[len(top) // 2]
        for r in top:
            if r.get("coverage", 1.0) <= typical - 0.15 and r.get("pickable", True):
                n = len([k for k in r.get("basis") or {} if metric_source(k)])
                out.append((r["score"], f"{md(r['name'])}: #{r.get('rank', '?')} for {e['title'].lower()} on "
                                        f"{n} signal{'s' if n != 1 else ''} ({round(100 * r['coverage'])}% of the "
                                        f"evidence)"))
    seen, lines = set(), []
    for _, line in sorted(out, key=lambda t: -t[0]):
        name = line.split(":", 1)[0]
        if name in seen:
            continue
        seen.add(name)
        lines.append(line)
        if len(lines) == limit:
            break
    return lines


def lab_table(jobs: dict, limit: int = 16) -> list[dict]:
    stats: dict[str, dict] = {}
    for e in jobs.values():
        for c in e.get("labs", []):
            s = stats.setdefault(c["lab"], {"lab": c["lab"], "first": 0, "top3": 0, "jobs": 0, "best_job": None,
                                            "best_of": 0})
            s["jobs"] += 1
            s["first"] += c.get("place", c["rank"]) == 1
            s["top3"] += c.get("place", c["rank"]) <= 3
            if c["of_best"] > s["best_of"]:
                s["best_of"], s["best_job"] = c["of_best"], f"{e['title']} ({c['name']})"
    rows = sorted(stats.values(), key=lambda s: (-s["first"], -s["top3"], -s["best_of"]))
    return rows[:limit]


def reflect(date: str, trust: dict, quarantined: dict, jobs: dict, history: dict,
            unmatched_entries: list[dict], community_data: dict | None, held: list[str]) -> str:
    lines = [f"# The brain, week of {date}", "",
             "Thalamus checks its own inputs every week before it trusts them, keeps a memory of past weeks and "
             "writes down here what it learned. The weekly sync rewrites this page. How each check works is at "
             "the bottom.", ""]

    lines += ["## Picks it held steady", ""]
    lines += [f"- {md(h)}" for h in held] or ["- None. Every best pick this week won by a clear margin or didn't change."]
    lines.append("")

    risers = []
    for j, e in jobs.items():
        for m in movers(history, j):
            if m.get("moved") and m["moved"] >= 3:
                risers.append((m["moved"], f"{md(m['name'])} up {m['moved']} places to #{m['now']} for {e['title'].lower()}"))
    lines += ["## Rising this week", ""]
    lines += [f"- {t}" for _, t in sorted(risers, key=lambda t: -t[0])[:12]] or [
        "- Nothing moved three places or more (or this is the first week on record)."]
    lines.append("")

    lines += ["## How much it trusts each source", "",
              "Agreement is the rank correlation between one source's view of every job and all the other "
              "sources' view, averaged over jobs. Sources measure different things, so the level varies a lot "
              "(a hallucination board barely tracks human preference). What counts is a sudden drop below the "
              "source's own usual level: that's what a broken feed looks like, and it costs the source weight "
              "in every job.", "",
              "| Source | Agreement this week | Usual | Trust | Last week |", "|---|---|---|---|---|"]
    for src, t in sorted(trust.items()):
        ag = t.get("agreement")
        lines.append(f"| {src} | {ag if ag is not None else 'n/a'} | {t.get('baseline', 'n/a')} | "
                     f"{t.get('trust', 1.0)} | {t.get('previous', 1.0)} |")
    lines.append("")

    lines += ["## Left out this week", ""]
    lines += [f"- `{m}`: {why}" for m, why in sorted(quarantined.items())] or [
        "- Nothing. Every metric looked consistent with last week."]
    lines.append("")

    lines += ["## Every lab, every job", "",
              "| Lab | Jobs won | Top 3 in | Strongest at |", "|---|---|---|---|"]
    for s in lab_table(jobs):
        lines.append(f"| {md(s['lab'])} | {s['first']} | {s['top3']} | {md(s['best_job'])}, {s['best_of']}% of the top score |")
    lines.append("")

    thin = _thin(jobs)
    lines += ["## What it can't judge well yet", "",
              "Strong models ranked on far less evidence than the others in the same table, usually because "
              "they're new and most leaderboards haven't tested them. Try them on low-stakes work "
              "(`thalamus scout <job>`) and file a verdict.", ""]
    lines += [f"- {t}" for t in thin] or ["- Nothing: every top model has about as much evidence as its peers."]
    lines.append("")

    lines += ["## Names it couldn't match", "",
              "Models a source scored that the brain couldn't tie to a callable model. An entry in "
              "`data/aliases.json` merges them next week.", ""]
    lines += [f"- {md(u['name'])} ({md(u.get('lab') or 'unknown lab')}): {u['signals']} signals, id `{md(u['id'])}`"
              for u in unmatched_entries[:12]] or ["- None."]
    lines.append("")

    votes = (community_data or {}).get("jobs", {})
    n_votes = sum(v.get("good", 0) + v.get("bad", 0) for job in votes.values() for v in job.values())
    lines += ["## Community verdicts", ""]
    if n_votes:
        lines.append(f"{n_votes} verdicts across {len(votes)} jobs, from accounts at least six months old. A model "
                     f"needs 5 different people before its score moves, and then by 10% at most. Votes never "
                     f"change the best pick.")
    else:
        lines.append("None yet. Anyone can add one: open a **Model verdict** issue in this repo, or run "
                     "`thalamus feedback <job> <model> good --share`.")
    lines += ["", "## How the checks work", "",
              f"- **Quarantine.** A metric whose rankings correlate under {QUARANTINE_RHO} with last week's, or "
              f"that lost more than {int(100 * (1 - LOST_SHARE))}% of its rows, is left out for the week.",
              f"- **Trust.** A source whose agreement with the others falls more than {DROP_ALLOWED} below its "
              f"usual level loses weight, down to {TRUST_MIN} at most, moving halfway each week. Steady sources "
              "keep full weight however different their view.",
              f"- **Steady picks.** A new best pick has to beat last week's by more than {STEADY_MARGIN} points.",
              f"- **Memory.** The top {HISTORY_DEPTH} for every job, for {HISTORY_WEEKS} weeks, in "
              "`data/history.json`.",
              "- **Community.** Verdicts filed as GitHub issues, counted once per person per model, from accounts "
              "at least six months old. They can't change the best pick.", ""]
    return "\n".join(lines)


def unmatched_entries(catalog: list[dict]) -> list[dict]:
    """Source-only text models (no callable id), strongest first: the matches most worth an alias."""
    rows = []
    for m in catalog:
        if ":" not in m["id"].split("@", 1)[0] or m.get("kind") != "llm" or m.get("unreleased") or m.get("variant"):
            continue
        metrics = m.get("metrics", {})
        variants = [v for v in catalog if v.get("base") == m["id"] and v.get("variant")]
        text = max([metrics.get("arena.text") or 0] + [(v.get("metrics") or {}).get("arena.text") or 0 for v in variants])
        rows.append({"id": m["id"], "name": m["name"], "lab": m.get("lab"), "arena": text,
                     "signals": len([k for k in metrics if metric_source(k)])})
    return sorted(rows, key=lambda r: (-r["arena"], -r["signals"], r["name"]))
