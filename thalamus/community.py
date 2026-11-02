"""Community verdicts: many brains, one consciousness.

Anyone can file a verdict through the "Model verdict" issue form. The weekly Action reads the
issues, keeps only counts, and the aggregate nudges the public rankings by at most +/-10%.

Issue text is attacker-controlled, so every field is validated against a strict pattern, nothing
from a body is logged or echoed, and the free-text note is never read. GitHub logins are used in
memory to count one vote per person and never reach the output file.

    python -m thalamus.community ingest --repo stephanochse/thalamus --out data/community.json
    python -m thalamus.community share code-build anthropic/claude-opus-5.5 good --beats z-ai/glm-5.3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MIN_VOTERS, SWING, K = 5, 0.2, 20
# Only accounts at least this old when they voted count, so a batch of fresh accounts can't stuff the vote.
MIN_ACCOUNT_DAYS = 180
MAX_ACCOUNT_LOOKUPS = 400
# A maintainer marks abuse with this label (or closes the issue as not planned or duplicate).
SPAM_LABEL = "spam"
SKIP_REASONS = {"not_planned", "duplicate"}
DEFAULT_REPO = "stephanochse/thalamus"
TEMPLATE = "verdict.yml"
_JOBS_FILE = Path(__file__).with_name("jobs.json")

_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._:/@-]{2,119}$")
_EMPTY = {"", "_no response_"}
_HEADINGS = {"job": "job", "model": "model", "verdict": "verdict", "beats": "beats"}


def _jobs() -> list[dict]:
    try:
        return json.loads(_JOBS_FILE.read_text(encoding="utf-8"))["jobs"]
    except (OSError, ValueError, KeyError):
        return []


def _clean_model(raw: str) -> str | None:
    value = raw.strip().strip("`").strip().lower()
    return value if _MODEL_RE.match(value) else None


def _sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if key is not None and key not in out:
            out[key] = "\n".join(buf).strip()

    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            flush()
            label = re.sub(r"\(.*?\)", "", line[4:]).strip().lower()
            key = _HEADINGS.get(label, "_other")
            buf = []
        elif key is not None:
            buf.append(line)
    flush()
    return out


def parse_issue_body(body: str, job_ids: set[str]) -> dict | None:
    """Return {"job","model","verdict","beats"} or None. The note field is dropped on purpose."""
    if not isinstance(body, str) or len(body) > 20000:
        return None
    sec = _sections(body)
    job_raw = sec.get("job", "").strip().lower()
    job = job_raw.split(" ", 1)[0] if job_raw else ""
    if job not in job_ids:
        return None
    verdict = sec.get("verdict", "").strip().lower()
    if verdict not in ("good", "bad"):
        return None
    model = _clean_model(sec.get("model", ""))
    if model is None:
        return None
    beats_raw = sec.get("beats", "").strip()
    beats = None
    if beats_raw.lower() not in _EMPTY:
        beats = _clean_model(beats_raw)
        if beats is None or beats == model:
            return None
    return {"job": job, "model": model, "verdict": verdict, "beats": beats}


def fetch_issues(repo: str, token: str | None, max_pages: int = 20) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("repo must look like owner/name")
    headers = _api_headers(token)
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        url = (f"https://api.github.com/repos/{repo}/issues?labels=verdict&state=all"
               f"&per_page=100&page={page}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                batch = json.loads(resp.read(20_000_000).decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"GitHub issues request failed: HTTP {err.code} on page {page}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            raise RuntimeError(f"GitHub issues request failed on page {page}: {type(err).__name__}") from None
        if not isinstance(batch, list):
            raise RuntimeError("GitHub issues request returned an unexpected payload")
        for item in batch:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            user = item.get("user") or {}
            rows.append({"user": user.get("login"), "user_type": user.get("type"),
                         "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
                         "body": item.get("body") or "", "state": item.get("state"),
                         "state_reason": item.get("state_reason"),
                         "labels": [str(lb.get("name", "")).lower() for lb in item.get("labels") or []
                                    if isinstance(lb, dict)]})
        if len(batch) < 100:
            return rows
    # A full last page means there are more issues than we read. A partial count would let a flood of
    # newer spam push real votes out of the window, so refuse and keep last week's counts.
    raise RuntimeError(f"more than {max_pages * 100} verdict issues; refusing a partial count")


def _api_headers(token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "thalamus-community"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_account_dates(logins: list[str], token: str | None, cap: int = MAX_ACCOUNT_LOOKUPS) -> dict[str, str]:
    """{login: account creation time} for up to `cap` voters. Logins that can't be looked up are left out,
    which means their votes don't count."""
    out: dict[str, str] = {}
    for login in sorted(set(logins))[:cap]:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login or ""):
            continue
        url = f"https://api.github.com/users/{urllib.parse.quote(login)}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_api_headers(token)), timeout=20) as resp:
                created = json.loads(resp.read(200_000).decode("utf-8")).get("created_at")
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
        if isinstance(created, str):
            out[login.lower()] = created
    return out


def _old_enough(account_created: str | None, voted_at: str | None, min_days: int) -> bool:
    from datetime import datetime
    try:
        made = datetime.fromisoformat(str(account_created).replace("Z", "+00:00"))
        when = datetime.fromisoformat(str(voted_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (when - made).days >= min_days


def aggregate(issues: list[dict], job_ids: set[str], accounts: dict[str, str] | None = None,
              min_account_days: int = MIN_ACCOUNT_DAYS) -> dict:
    """accounts: {login: account creation time}. When given, only accounts at least min_account_days old at
    the time of the vote count."""
    latest: dict[tuple[str, str, str], tuple[str, str]] = {}
    valid = 0
    for issue in issues:
        if issue.get("user_type") != "User" or not issue.get("user"):
            continue
        # a maintainer rejects a vote by closing it as not planned or duplicate, or by labelling it spam
        if issue.get("state_reason") in SKIP_REASONS or SPAM_LABEL in (issue.get("labels") or []):
            continue
        if accounts is not None and not _old_enough(accounts.get(str(issue["user"]).lower()),
                                                    issue.get("created_at"), min_account_days):
            continue
        parsed = parse_issue_body(issue.get("body") or "", job_ids)
        if parsed is None:
            continue
        valid += 1
        stamp = str(issue.get("updated_at") or issue.get("created_at") or "")
        votes = [(parsed["model"], parsed["verdict"])]
        if parsed["beats"]:
            votes = [(parsed["model"], "good"), (parsed["beats"], "bad")]
        for model, verdict in votes:
            key = (str(issue["user"]).lower(), parsed["job"], model)
            if key not in latest or stamp >= latest[key][0]:
                latest[key] = (stamp, verdict)
    jobs: dict[str, dict[str, dict[str, int]]] = {}
    for (_user, job, model), (_stamp, verdict) in latest.items():
        cell = jobs.setdefault(job, {}).setdefault(model, {"good": 0, "bad": 0, "voters": 0})
        cell[verdict] += 1
        cell["voters"] += 1
    return {"jobs": jobs, "issues_read": len(issues), "valid": valid}


def factor(good: int, bad: int, voters: int) -> float:
    """Multiplier for a model's public score. 1.0 until MIN_VOTERS people have voted."""
    if voters < MIN_VOTERS:
        return 1.0
    n = good + bad
    if n <= 0:
        return 1.0
    mean = (good + 1) / (n + 2)
    return 1 + SWING * (mean - 0.5) * n / (n + K)


def load(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"jobs": {}}
    return data if isinstance(data, dict) and isinstance(data.get("jobs"), dict) else {"jobs": {}}


def write(path, data: dict) -> None:
    out = {**data, "updated": time.strftime("%Y-%m-%d", time.gmtime()),
           "note": "Counts only. No usernames, notes or issue text are stored."}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def share_url(job: str, model: str, verdict: str, beats: str | None = None,
              repo: str = DEFAULT_REPO) -> str:
    # Validated like an incoming issue, so an agent can't put arbitrary text into a public issue link.
    title = next((j["title"] for j in _jobs() if j["id"] == job), None)
    if title is None or verdict not in ("good", "bad") or _clean_model(model) != model.strip().lower():
        raise ValueError("share_url needs a known job, a model id like org/name and good or bad")
    if beats and _clean_model(beats) != beats.strip().lower():
        raise ValueError("beats must be a model id like org/name")
    # A dropdown only prefills when the value equals the option text, "<id> (<title>)".
    params = {"template": TEMPLATE, "title": f"verdict: {job} {model}",
              "job": f"{job} ({title})" if title else job, "model": model, "verdict": verdict}
    if beats:
        params["beats"] = beats
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://github.com/{repo}/issues/new?{query}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="thalamus.community")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("--repo", default=DEFAULT_REPO)
    ing.add_argument("--out", default="data/community.json")
    sh = sub.add_parser("share")
    sh.add_argument("job")
    sh.add_argument("model")
    sh.add_argument("verdict", choices=["good", "bad"])
    sh.add_argument("--beats")
    sh.add_argument("--repo", default=DEFAULT_REPO)
    args = ap.parse_args(argv)
    if args.cmd == "share":
        print(share_url(args.job, args.model, args.verdict, args.beats, args.repo))
        return 0
    ids = {j["id"] for j in _jobs()}
    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        issues = fetch_issues(args.repo, token)
    except (RuntimeError, ValueError) as err:
        print(f"community ingest failed: {err}", file=sys.stderr)
        return 1
    voters = [i["user"] for i in issues if i.get("user") and parse_issue_body(i.get("body") or "", ids)]
    agg = aggregate(issues, ids, accounts=fetch_account_dates(voters, token))
    write(args.out, agg)
    models = {m for per in agg["jobs"].values() for m in per}
    print(f"community: {agg['issues_read']} issues read, {agg['valid']} valid, "
          f"{len(agg['jobs'])} jobs, {len(models)} models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
