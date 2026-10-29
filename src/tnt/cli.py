"""tnt: scrape -> clean -> load -> query T&T stores in the Lower Mainland."""

import argparse
import json
import sys
from datetime import date
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


def _runs(before: str | None = None) -> list:
    from tnt.schema import Run

    return [Run.model_validate_json(p.read_text()) for p in sorted(CLEAN_DIR.glob("*.json"))
            if before is None or p.stem < before]


def cmd_clean(args):
    from tnt.geocode import Geocoder
    from tnt.pipeline import run
    from tnt.resolve import History, load_decisions

    raw = Path(args.raw) if args.raw else _latest(RAW_DIR)
    # Earlier runs only: re-cleaning a day shouldn't depend on its own last output.
    earlier = _runs(before=raw.stem)
    result = run(raw, None if args.no_geocode else Geocoder(), History.from_runs(earlier), load_decisions())
    out = _clean_path(raw)
    out.write_text(result.model_dump_json(indent=1) + "\n")
    flagged = [s for s in result.stores if s.flags]
    kept_ids = sum(s.matched_by != "new" for s in result.stores)
    print(f"{len(result.stores)} Lower Mainland stores -> {out} ({len(flagged)} flagged, "
          f"{kept_ids} kept their IDs from {len(earlier)} earlier run(s))")
    for s in flagged:
        extra = f" (candidate: {s.relocation_candidate})" if s.relocation_candidate else ""
        print(f"  {s.name} {s.location_id}: {', '.join(s.flags)}{extra}")
    for e in result.excluded:
        print(f"  excluded {e.name} ({e.city}): {e.reason}")


def cmd_link(args):
    from tnt.resolve import DECISIONS

    for loc in (args.from_location, args.to_location):
        if not loc.startswith("loc_"):
            sys.exit(f"{loc} is not a location_id (loc_...)")
    data = json.loads(DECISIONS.read_text()) if DECISIONS.exists() else {"relocations": []}
    if any(d["to"] == args.to_location for d in data["relocations"]):
        sys.exit(f"{args.to_location} is already linked")
    data["relocations"].append({"from": args.from_location, "to": args.to_location,
                                "decided_on": date.today().isoformat(), "note": args.note})
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"linked {args.from_location} -> {args.to_location}; run `tnt clean` to apply")


def cmd_load(args):
    from tnt import db

    runs = _runs()
    with db.connect() as conn:
        db.load(conn, runs)
    print(f"rebuilt the database from {len(runs)} run(s) in {CLEAN_DIR}/")


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
    from tnt.schema import Run

    before, after = (Run.model_validate_json(Path(p).read_text()) for p in (args.before, args.after))
    d = diff_runs(before, after)
    counts = ", ".join(f"{t} {sum(e.type == t for e in d.events)}" for t in ("opened", "closed", "relocated", "reopened"))
    print(f"{counts}, changed {len(d.changed)}")
    for e in d.events:
        moved = f" from {e.from_location_id}" if e.from_location_id else ""
        print(f"  {e.type} {e.store_id} at {e.location_id}{moved}")
    for loc, fields in d.changed.items():
        print(f"  changed {loc}: {', '.join(fields)}")


def cmd_compare_llm(args):
    from tnt.compare import compare

    compare(Path(args.clean) if args.clean else None)


def cmd_schema(args):
    import json

    from tnt.schema import Run

    print(json.dumps(Run.model_json_schema(), indent=2))


def cmd_serve(args):
    import uvicorn

    uvicorn.run("tnt.api:app", port=args.port)


def main():
    p = argparse.ArgumentParser(prog="tnt")
    sub = p.add_subparsers(required=True)
    sub.add_parser("scrape", help="load the store locator once and save raw JSON responses").set_defaults(fn=cmd_scrape)
    s = sub.add_parser("import", help="import a HAR/JSON saved from your browser")
    s.add_argument("file")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("clean", help="raw -> cleaned, geocoded, flagged stores")
    s.add_argument("raw", nargs="?")
    s.add_argument("--no-geocode", action="store_true")
    s.set_defaults(fn=cmd_clean)
    sub.add_parser("load", help="rebuild the database from every cleaned run").set_defaults(fn=cmd_load)
    s = sub.add_parser("link", help="record a relocation a person confirmed")
    s.add_argument("from_location")
    s.add_argument("to_location")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_link)
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
    sub.add_parser("schema", help="print the JSON Schema for cleaned runs").set_defaults(fn=cmd_schema)
    s = sub.add_parser("serve", help="run the FastAPI app")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args()
    args.fn(args)
