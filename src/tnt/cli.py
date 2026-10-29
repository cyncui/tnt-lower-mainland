"""tnt: scrape -> clean -> load -> query T&T stores in the Lower Mainland."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAW_DIR = Path("data/raw")
CLEAN_DIR = Path("data/clean")


def _latest(directory: Path) -> Path:
    files = sorted(directory.glob("*.json"))
    if not files:
        sys.exit(f"no files in {directory}/; run `tnt scrape` or `tnt import` first")
    return files[-1]


def _clean_path(raw: Path) -> Path:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    return CLEAN_DIR / raw.name


def cmd_scrape(args):
    from tnt.scrape import Blocked, scrape

    try:
        print(f"saved {scrape()}")
    except Blocked as e:
        sys.exit(f"scrape stopped: {e}\nsave the response from your own browser and run `tnt import <file>`")


def cmd_import(args):
    from tnt.scrape import import_capture

    print(f"saved {import_capture(Path(args.file))}")


def cmd_clean(args):
    from tnt.geocode import Geocoder
    from tnt.pipeline import run

    raw = Path(args.raw) if args.raw else _latest(RAW_DIR)
    stores = run(raw, None if args.no_geocode else Geocoder())
    out = _clean_path(raw)
    out.write_text(json.dumps([s.as_dict() for s in stores], indent=1, ensure_ascii=False))
    flagged = [s for s in stores if s.flags]
    print(f"{len(stores)} Lower Mainland stores -> {out} ({len(flagged)} flagged)")
    for s in flagged:
        print(f"  {s.name or s.raw_address}: {', '.join(s.flags)}")


def cmd_load(args):
    from tnt import db

    paths = [Path(p) for p in args.files] or sorted(CLEAN_DIR.glob("*.json"))
    with db.connect() as conn:
        for p in paths:
            db.load(conn, json.loads(p.read_text()), date.fromisoformat(p.stem))
            print(f"loaded {p}")


def cmd_query(args):
    from tnt import db

    with db.connect() as conn:
        names = [args.name] if args.name else list(db.named_queries())
        for name in names:
            print(f"\n== {name}")
            for row in db.run_query(conn, name):
                print("  " + "  ".join(f"{k}={v}" for k, v in row.items()))


def cmd_diff(args):
    from tnt.diff import diff_runs

    before, after = (json.loads(Path(p).read_text()) for p in (args.before, args.after))
    d = diff_runs(before, after)
    print(f"added {len(d.added)}, removed {len(d.removed)}, changed {len(d.changed)}")
    for sid in d.added:
        print(f"  + {sid}")
    for sid in d.removed:
        print(f"  - {sid}")
    for sid, fields in d.changed.items():
        print(f"  ~ {sid}: {', '.join(fields)}")


def cmd_compare_llm(args):
    from tnt.compare import compare

    compare(Path(args.clean) if args.clean else None)


def cmd_serve(args):
    import uvicorn

    uvicorn.run("tnt.api:app", port=args.port)


def main():
    p = argparse.ArgumentParser(prog="tnt")
    sub = p.add_subparsers(required=True)
    sub.add_parser("scrape", help="load the store locator once and save raw GraphQL").set_defaults(fn=cmd_scrape)
    s = sub.add_parser("import", help="import a HAR/JSON saved from your browser")
    s.add_argument("file")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("clean", help="raw -> cleaned, geocoded, flagged stores")
    s.add_argument("raw", nargs="?")
    s.add_argument("--no-geocode", action="store_true")
    s.set_defaults(fn=cmd_clean)
    s = sub.add_parser("load", help="load cleaned runs into Postgres")
    s.add_argument("files", nargs="*")
    s.set_defaults(fn=cmd_load)
    s = sub.add_parser("query", help="run the named SQL queries")
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_query)
    s = sub.add_parser("diff", help="compare two cleaned runs")
    s.add_argument("before")
    s.add_argument("after")
    s.set_defaults(fn=cmd_diff)
    s = sub.add_parser("compare-llm", help="regex vs LLM cleaning, side by side")
    s.add_argument("clean", nargs="?")
    s.set_defaults(fn=cmd_compare_llm)
    s = sub.add_parser("serve", help="run the FastAPI app")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args()
    args.fn(args)
