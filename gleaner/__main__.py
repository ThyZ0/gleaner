"""gleaner                     open the app on your usual folders
gleaner FOLDER...           open the app on these folders
gleaner scan [FOLDER...]    list document families in the terminal
gleaner show FILE           versions of one document, and what never reached the latest
gleaner show FILE --merge   also write "<latest> (gleaned)" with those passages put back
add --json to scan/show for machine-readable output (used by the Claude Code skill)."""
import argparse
import json
import os
import sys
from datetime import datetime

from . import __version__, core, merge
from .server import default_roots, serve


def when(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def short(text, n=110):
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def load(roots, quiet):
    def tick(n, total, _):
        if not quiet and sys.stderr.isatty() and (n % 25 == 0 or n == total):
            sys.stderr.write(f"\rreading {n}/{total} files")
            sys.stderr.flush()
    docs, problems = core.scan(roots, progress=tick)
    if not quiet and sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 40 + "\r")
    return docs, problems


def cmd_scan(args):
    roots = args.folders or default_roots()
    docs, problems = load(roots, args.json)
    reports = sorted((core.report(f) for f in core.families(docs)), key=lambda r: -r["score"])
    if not args.all:
        reports = [r for r in reports if not r["received"]]
    if args.json:
        print(json.dumps({"documents": len(docs), "unreadable": problems, "families": [
            {"name": r["name"], "versions": len(r["versions"]), "stranded": len(r["stranded"]),
             "latest": r["versions"][r["head"]]["files"][0]["path"],
             "files": [f["path"] for v in r["versions"] for f in v["files"]]} for r in reports]},
            ensure_ascii=False, indent=1))
        return
    print(f"{len(docs)} documents read in {', '.join(roots)}")
    if problems:
        print(f"{len(problems)} could not be read (gleaner scan --json lists them)")
    if not reports:
        print("No document exists in several versions here.")
        return
    print()
    for r in reports:
        head = r["versions"][r["head"]]
        flag = f"  ⚑ {len(r['stranded'])} passage(s) never reached the latest" if r["stranded"] else ""
        print(f"{r['name']}  ·  {len(r['versions'])} versions, {r['files']} files{flag}")
        print(f"    latest: {head['files'][0]['path']}  ({when(head['time'])})")
    hidden = "" if args.all else " PDF-only families (documents you probably received) are hidden: --all shows them."
    print(f"\ngleaner show FILE  tells the story of one of them.{hidden}")


def cmd_show(args):
    target = os.path.normcase(os.path.abspath(args.file))
    if not os.path.isfile(target):
        sys.exit(f"no such file: {args.file}")
    roots = args.folders or [os.path.dirname(target)]
    docs, _ = load(roots, args.json)
    doc = next((d for d in docs if os.path.normcase(d.path) == target), None)
    if doc is None:
        sys.exit("this file could not be read as a document (supported: docx pptx odt odp pdf txt md tex)")
    fam = next((f for f in core.families(docs) if doc in f), None)
    if fam is None:
        if args.json:
            print(json.dumps({"file": doc.path, "versions": []}))
        else:
            print(f"No other version of this document in {', '.join(roots)}.")
            if not args.folders:
                print("Copies elsewhere? Add the folders to search: gleaner show FILE FOLDER...")
        return
    r = core.report(fam)
    if args.merge and r["stranded"]:
        _, head, _ = core.analyse(fam)
        try:
            r["merged"] = merge.merged_copy(head["doc"], r["stranded"])
        except ValueError as e:
            sys.exit(str(e))
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"{r['name']}: {len(r['versions'])} versions\n")
    if r["suspect"] is not None:
        print(f"! The newest file may be an old or partial copy with a recent date: v{r['suspect'] + 1} holds all of it, plus passages missing from it.\n")
    for v in reversed(r["versions"]):
        mark = "●" if v["is_head"] else "○"
        parent = f"  from v{v['parent'] + 1}" if v["parent"] is not None else ""
        print(f" {mark} v{v['n'] + 1}  {when(v['time'])}  {v['words']} words{parent}")
        for f in v["files"]:
            print(f"      {f['path']}")
    if r["stranded"]:
        print(f"\n⚑ {len(r['stranded'])} passage(s) written in another copy never reached the latest version:")
        for s in r["stranded"]:
            print(f"\n  from v{s['source'] + 1}: «{short(s['text'], 300)}»")
            if s["after"]:
                print(f"    belongs after: «{short(s['after'], 80)}»")
    else:
        print("\nEverything written in the other copies is in the latest version (or was deleted on purpose along the way).")
    if r["removed"]:
        print(f"\n{len(r['removed'])} passage(s) were deleted along the way (the app shows them).")
    if r.get("merged"):
        print(f"\nWrote {r['merged']}\n(the passages are highlighted; the original is unchanged)")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # pipes on Windows default to cp1252 and crash on « ● »
    if argv and argv[0] in ("scan", "show"):
        p = argparse.ArgumentParser(prog=f"gleaner {argv[0]}")
        if argv[0] == "show":
            p.add_argument("file")
        p.add_argument("folders", nargs="*")
        p.add_argument("--json", action="store_true")
        if argv[0] == "scan":
            p.add_argument("--all", action="store_true", help="include PDF-only families")
        else:
            p.add_argument("--merge", action="store_true", help="write a copy of the latest with the passages put back")
        args = p.parse_args(argv[1:])
        args.folders = [os.path.abspath(f) for f in args.folders]
        return cmd_scan(args) if argv[0] == "scan" else cmd_show(args)
    p = argparse.ArgumentParser(prog="gleaner", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folders", nargs="*")
    p.add_argument("--port", type=int, default=7341)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    roots = [os.path.abspath(f) for f in args.folders] or default_roots()
    missing = [r for r in roots if not os.path.isdir(r)]
    if missing:
        sys.exit(f"not a folder: {', '.join(missing)}")
    serve(roots, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
