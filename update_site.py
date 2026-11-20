#!/usr/bin/env python3
"""
update_site.py — drop a fresh ai-market-prices.csv in this folder and run:

    python update_site.py

It does two things, in order:

  1. IMAGES — runs download_images.py (unmodified, right next to this file)
     so every resource_id / asset_id in the CSV that doesn't have a picture
     in images/ yet gets one fetched. Already-downloaded pictures are left
     alone, so this step is incremental and safe to re-run; it naturally
     only does work for brand-new cards. Skip it with --no-images.

  2. PAGE — rewrites the `const DATA = [...]` array inside the HTML page
     straight from the CSV. The page's table and its card view both render
     from that one array at load time, so this single rewrite is all it
     takes for new players, changed prices/ratings, or removed players to
     show up in BOTH views. Nothing else in the HTML file is touched.

  3. PUBLISH — if this folder is a git repo (see ONE-TIME SETUP below),
     commits every changed file (the HTML page, any newly downloaded
     images, the CSV itself) and pushes to its remote. GitHub Pages
     rebuilds from that push automatically, so your friends' browsers
     show the update within about a minute, no manual upload needed.
     Skip it with --no-push. If the folder isn't a git repo yet, this
     step prints the one-time setup instructions below and otherwise
     does nothing (your local files are still updated).

Expected folder layout (same as you already have):
  ai-market-prices.csv     <- replace this with a new export any time
  ai-market-prices.html    <- gets its DATA array rewritten in place
  download_images.py      <- used as-is for step 1
  images/                  <- downloaded pictures live here

Usage:
    python update_site.py                      # use the default file names above
    python update_site.py other.csv page.html   # override either path
    python update_site.py --no-images           # skip the picture-download step
    python update_site.py --no-push             # skip the git commit/push step
    python update_site.py --no-backup           # don't write page.html.bak

Needs Python 3. Step 1 and step 3 also need an internet connection; step 2
does not.

ONE-TIME SETUP for GitHub Pages (do this once, in this folder):
    git init
    git add -A
    git commit -m "Initial site"
    git branch -M main
    git remote add origin https://github.com/<you>/<repo>.git
    git push -u origin main
  Then on GitHub: repo Settings -> Pages -> Source: "Deploy from a branch",
  branch "main", folder "/ (root)" -> Save. Your friends' link will be
  https://<you>.github.io/<repo>/ai-market-prices.html (or rename the file
  to index.html beforehand, and pass that name to this script, so the link
  has no filename on the end).
  After that one-time setup, every future `python update_site.py` run also
  pushes, so the live page always matches your local folder.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# CSV column name -> required? (False means blank is allowed and becomes null)
NUMERIC_FIELDS = [
    ("rating", True),
    ("resource_id", True),
    ("asset_id", True),
    ("reference_coins", True),
    ("buyer_reference_coins", False),
    ("observations", True),
    ("active_ai_listings", True),
    ("active_ai_starting_bids_coins", False),
    ("active_ai_buy_now_prices_coins", False),
]
REQUIRED_HEADER = [
    "player", "rating", "card_type", "resource_id", "asset_id",
    "reference_coins", "buyer_reference_coins", "reference_source",
    "observations", "exact_history", "active_ai_listings",
    "active_ai_starting_bids_coins", "active_ai_buy_now_prices_coins",
]  # reference_updated_utc is read if present but isn't used on the page

START_MARKER = "const DATA=["
END_MARKER = "\n];\n</script>"


def find_data_span(content: str):
    try:
        marker_pos = content.index(START_MARKER)
    except ValueError:
        raise SystemExit("Could not find 'const DATA=[' in the HTML file.")
    array_start = marker_pos + len("const DATA=")
    try:
        end_pos = content.index(END_MARKER, array_start)
    except ValueError:
        raise SystemExit("Found the start of the DATA array but not its expected end.")
    return array_start, end_pos + 2


def pint(rec, key, label, required):
    v = (rec.get(key) or "").strip()
    if v == "":
        if required:
            raise SystemExit(f"Row '{label}': {key} is required but blank.")
        return None
    try:
        return int(v)
    except ValueError:
        raise SystemExit(f"Row '{label}': {key} = {v!r} is not a valid whole number.")


def load_csv_rows(csv_path: Path):
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [h for h in REQUIRED_HEADER if h not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(
                "CSV is missing required column(s): " + ", ".join(missing) +
                f"\nExpected header to include: {', '.join(REQUIRED_HEADER)}"
            )
        rows = []
        for line_no, rec in enumerate(reader, start=2):
            name = (rec.get("player") or "").strip()
            if name == "":
                continue
            label = f"{name} (csv line {line_no})"
            row = [
                name,
                pint(rec, "rating", label, True),
                (rec.get("card_type") or "").strip(),
                pint(rec, "resource_id", label, True),
                pint(rec, "asset_id", label, True),
                pint(rec, "reference_coins", label, True),
                pint(rec, "buyer_reference_coins", label, False),
                (rec.get("reference_source") or "").strip(),
                pint(rec, "observations", label, True),
                (rec.get("exact_history") or "").strip().lower() in ("true", "1", "yes"),
                pint(rec, "active_ai_listings", label, True),
                pint(rec, "active_ai_starting_bids_coins", label, False),
                pint(rec, "active_ai_buy_now_prices_coins", label, False),
            ]
            rows.append(row)
    return rows


def load_existing_data(html_path: Path):
    if not html_path.exists():
        return []
    content = html_path.read_text(encoding="utf-8")
    try:
        s, e = find_data_span(content)
    except SystemExit:
        return []
    return json.loads(content[s:e])


def run_image_download():
    script = HERE / "download_images.py"
    if not script.exists():
        print(f"(skipping image download: {script.name} not found next to this script)")
        return
    print("=== Step 1: fetching pictures for any new cards (download_images.py) ===")
    result = subprocess.run([sys.executable, str(script)], cwd=str(HERE))
    if result.returncode != 0:
        print(f"download_images.py exited with code {result.returncode} — continuing anyway.")


def update_html(csv_path: Path, html_path: Path, no_backup: bool):
    print("=== Step 2: rewriting the page's data from the CSV ===")
    old_rows = load_existing_data(html_path)
    old_ids = {r[3] for r in old_rows}
    old_by_id = {r[3]: r[0] for r in old_rows}

    new_rows = load_csv_rows(csv_path)
    if not new_rows:
        raise SystemExit("No data rows found in the CSV — refusing to write an empty page.")
    new_ids = {r[3] for r in new_rows}

    added = [r for r in new_rows if r[3] not in old_ids]
    removed_ids = old_ids - new_ids

    content = html_path.read_text(encoding="utf-8")
    array_start, array_end = find_data_span(content)
    array_text = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in new_rows) + "\n]"
    new_content = content[:array_start] + array_text + content[array_end:]

    if not no_backup:
        backup_path = html_path.with_suffix(html_path.suffix + ".bak")
        backup_path.write_text(content, encoding="utf-8")
        print(f"Backed up previous version to {backup_path.name}")

    html_path.write_text(new_content, encoding="utf-8")

    print(f"Wrote {len(new_rows)} cards to {html_path.name}")
    if added:
        print(f"  {len(added)} new card(s):")
        for r in added[:30]:
            print(f"    + {r[0]} ({r[2]}, resource_id {r[3]})")
        if len(added) > 30:
            print(f"    ...and {len(added) - 30} more")
    if removed_ids:
        print(f"  {len(removed_ids)} card(s) no longer in the CSV were dropped:")
        for rid in list(removed_ids)[:30]:
            print(f"    - {old_by_id.get(rid, '?')} (resource_id {rid})")
        if len(removed_ids) > 30:
            print(f"    ...and {len(removed_ids) - 30} more")
    if not added and not removed_ids:
        print("  (no new or removed cards — only values may have changed)")

    bits = [f"{len(new_rows)} cards"]
    if added:
        bits.append(f"+{len(added)} new")
    if removed_ids:
        bits.append(f"-{len(removed_ids)} removed")
    return ", ".join(bits)


def push_to_github(summary: str):
    print("=== Step 3: publishing to GitHub (git commit + push) ===")
    git = shutil.which("git")
    if not git:
        print("  git isn't installed/found on PATH — skipping. Install git to enable auto-publish.")
        return
    if not (HERE / ".git").exists():
        print(
            "  This folder isn't a git repo yet, so there's nothing to push.\n"
            "  Run the ONE-TIME SETUP steps from this script's --help text once,\n"
            "  then future runs will publish automatically."
        )
        return

    # git itself is now the real history/backup, so don't let the rolling
    # .bak file (always one version behind) cause a spurious commit every
    # run — keep it out of version control entirely.
    gitignore = HERE / ".gitignore"
    ignore_line = "*.bak"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ignore_line not in existing.splitlines():
        with gitignore.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(ignore_line + "\n")

    def run(*cmd, **kw):
        return subprocess.run(["git"] + list(cmd), cwd=str(HERE), text=True,
                               capture_output=True, **kw)

    remote = run("remote")
    if not remote.stdout.strip():
        print("  No git remote configured — add one with 'git remote add origin <url>' then push manually once.")
        return

    add_res = run("add", "-A")
    if add_res.returncode != 0:
        print("  'git add' failed:", add_res.stderr.strip())
        return

    status = run("status", "--porcelain")
    if not status.stdout.strip():
        print("  No changes to publish — already up to date.")
        return

    commit_msg = f"Update data: {summary}"
    commit_res = run("commit", "-m", commit_msg)
    if commit_res.returncode != 0:
        print("  'git commit' failed:", commit_res.stderr.strip())
        return
    print(f"  Committed: {commit_msg}")

    branch_res = run("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_res.stdout.strip() or "HEAD"
    has_upstream = run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode == 0
    push_res = run("push", "-u", "origin", branch) if not has_upstream else run("push")
    if push_res.returncode != 0:
        print("  'git push' failed — your changes are committed locally but not published yet.")
        print("  ", push_res.stderr.strip().splitlines()[-1] if push_res.stderr.strip() else "")
        print("  Fix the issue (auth, network, upstream branch) and run 'git push' by hand.")
        return
    print("  Pushed. GitHub Pages will update the live page shortly.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", nargs="?", default="ai-market-prices.csv", help="CSV file (default: ai-market-prices.csv)")
    p.add_argument("html", nargs="?", default="ai-market-prices.html", help="HTML page (default: ai-market-prices.html)")
    p.add_argument("--no-images", action="store_true", help="Skip running download_images.py")
    p.add_argument("--no-push", action="store_true", help="Skip the git commit/push (GitHub Pages) step")
    p.add_argument("--no-backup", action="store_true", help="Don't write a .bak backup of the HTML")
    args = p.parse_args()

    csv_path = (HERE / args.csv) if not Path(args.csv).is_absolute() else Path(args.csv)
    html_path = (HERE / args.html) if not Path(args.html).is_absolute() else Path(args.html)

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    if not html_path.exists():
        raise SystemExit(f"HTML page not found: {html_path}")

    if not args.no_images:
        run_image_download()
    else:
        print("(skipping image download step)")

    summary = update_html(csv_path, html_path, args.no_backup)

    if not args.no_push:
        push_to_github(summary)
    else:
        print("(skipping git publish step)")

    print("\nDone. Open the HTML page to see the update.")


if __name__ == "__main__":
    main()
