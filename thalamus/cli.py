"""thalamus command line.

    thalamus update [--only a,b]                  weekly sync (what the GitHub Action runs)
    thalamus update --personal --with aa          your own build with opt-in sources (~/.thalamus/data)
    thalamus route "task text" [--job J] [--budget best|value|budget|fast|open]
    thalamus top <job> [-n 10] [--labs]           leaderboard for one job (--labs: every lab's best model)
    thalamus jobs                                 every job and what it covers
    thalamus council --tier deep --file task.md --draft mine.md --host claude
    thalamus ask --model <seat|openrouter-slug> --prompt "..."
    thalamus seats [--tier max --host claude]     who would sit on the council
    thalamus feedback <job> <model> good|bad [--note ...] [--share]   teach it your taste (--share: also
                                                  print a link to add your verdict to the public rankings)
    thalamus community ingest|share ...           community verdicts filed as GitHub issues
    thalamus brain                                what this week's self-check found (BRAIN.md)
    thalamus learn                                what your feedback has taught it so far
    thalamus scout <job>                          an untried strong model to test on your next task
    thalamus media --platform higgsfield          this week's image/video/voice picks on your platform
    thalamus doctor [--live]                      check every login and lane
    thalamus install [--check|--dry-run|--only a,b|--uninstall]
    thalamus mcp                                  run the MCP server (tools call this)
"""
from __future__ import annotations

import argparse
import json
import sys


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    if cmd == "update":
        ap = argparse.ArgumentParser(prog="thalamus update")
        ap.add_argument("--only")
        ap.add_argument("--offline", action="store_true")
        ap.add_argument("--with", dest="extra", help="opt-in sources, e.g. aa,epoch_external,benchlm,eqbench")
        ap.add_argument("--personal", action="store_true",
                        help="build into ~/.thalamus/data with opt-in sources; never touches the repo")
        a = ap.parse_args(rest)
        from . import update
        update.run(only=a.only.split(",") if a.only else None, offline=a.offline,
                   extra=a.extra.split(",") if a.extra else None, personal=a.personal)
        return 0
    if cmd == "route":
        ap = argparse.ArgumentParser(prog="thalamus route")
        ap.add_argument("task")
        ap.add_argument("--job")
        ap.add_argument("--budget")
        a = ap.parse_args(rest)
        from . import routes
        _print(routes.route(a.task, job=a.job, budget=a.budget))
        return 0
    if cmd == "top":
        ap = argparse.ArgumentParser(prog="thalamus top")
        ap.add_argument("job")
        ap.add_argument("-n", type=int, default=10)
        ap.add_argument("--labs", action="store_true", help="the best model from every lab instead")
        a = ap.parse_args(rest)
        from . import routes
        board = routes.leaderboard(a.job, n=a.n)
        print(f"{board['title']} (week of {board['updated']})")
        if a.labs:
            for c in board["every_lab"]:
                print(f"{c['lab']:<20} {c['name']:<40} #{c['rank']:<4} {c['of_best']:>3}% of the top")
            return 0
        for r in board["rows"]:
            price = f"${r['price']:.3f}" if r.get("price") is not None else "n/a"
            print(f"{r['rank']:>3}. {r['name']:<42} {r.get('lab') or '':<18} score {r['score']:>5}  {price}")
        return 0
    if cmd == "jobs":
        from . import routes
        for j in routes.jobs():
            print(f"{j['id']:<16} [{j['group']}] {j['title']}")
        return 0
    if cmd in ("council", "ask", "seats", "show"):
        from . import council
        mapped = {"council": "run"}.get(cmd, cmd)
        return council.main([mapped] + rest) or 0
    if cmd == "doctor":
        from . import doctor
        print(doctor.render(doctor.check(live="--live" in rest)))
        return 0
    if cmd in ("feedback", "learn", "scout"):
        from . import learn
        share = cmd == "feedback" and "--share" in rest
        code = learn.main([cmd] + [r for r in rest if r != "--share"]) or 0
        if share and code == 0:
            from . import community
            pos = [r for r in rest if not r.startswith("--")]
            beats = rest[rest.index("--beats") + 1] if "--beats" in rest else None
            verdict = pos[2] if len(pos) > 2 and pos[2] in ("good", "bad") else "good"
            print("Add it to the public rankings (opens a prefilled GitHub issue):")
            print(community.share_url(pos[0], pos[1], verdict, beats))
        return code
    if cmd == "community":
        from . import community
        return community.main(rest) or 0
    if cmd == "brain":
        from .paths import DATA, PERSONAL_DATA, REPO
        for path in (PERSONAL_DATA / "BRAIN.md", REPO / "BRAIN.md"):
            if path.exists():
                print(path.read_text(encoding="utf-8"))
                return 0
        print("No BRAIN.md yet. Run `thalamus update` first.", file=sys.stderr)
        return 1
    if cmd == "media":
        from . import platforms
        return platforms.main(rest) or 0
    if cmd == "install":
        from . import install
        return install.main(rest) or 0
    if cmd == "mcp":
        from . import mcp_server
        mcp_server.main()
        return 0
    print(f"Unknown command '{cmd}'.\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
