#!/usr/bin/env python3
"""
run.py — One-click Golf SG Toolkit Launcher
════════════════════════════════════════════
Just run:  python run.py

This script guides you through the full pipeline interactively:
  1. Fetches your golf rounds from Garmin Connect
  2. Parses shots into a CSV
  3. Calculates strokes gained per shot
  4. Formats per-hole scorecard rows
  5. Uploads to Google Sheets (optional)

First-time setup takes ~2 minutes. After that, one command does everything.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

# ── ensure we can import our modules ─────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── colour helpers (work on Mac/Linux; graceful fallback on Windows) ──────────
def _supports_colour():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.name != "nt"

if _supports_colour():
    G  = "\033[32m"   # green
    Y  = "\033[33m"   # yellow
    C  = "\033[36m"   # cyan
    R  = "\033[31m"   # red
    B  = "\033[1m"    # bold
    RS = "\033[0m"    # reset
else:
    G = Y = C = R = B = RS = ""

def banner():
    print(f"""
{C}{B}╔══════════════════════════════════════════════╗
║        ⛳  Golf Strokes Gained Toolkit        ║
╚══════════════════════════════════════════════╝{RS}
""")

def step(n, title):
    print(f"\n{B}{C}── Step {n}: {title} {RS}")
    print("─" * 50)

def ok(msg):   print(f"  {G}✓{RS}  {msg}")
def warn(msg): print(f"  {Y}⚠{RS}   {msg}")
def err(msg):  print(f"  {R}✗{RS}  {msg}")
def info(msg): print(f"     {msg}")


# ── dependency checker ────────────────────────────────────────────────────────

REQUIRED_PACKAGES = {
    "garminconnect": "garminconnect",
    "garth":         "garth",
    "requests":      "requests",
}
OPTIONAL_PACKAGES = {
    "google.oauth2":           "google-auth",
    "google_auth_oauthlib":    "google-auth-oauthlib",
    "googleapiclient":         "google-api-python-client",
}

def check_dependencies():
    missing_required = []
    missing_optional = []

    for module, pkg in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing_required.append(pkg)

    for module, pkg in OPTIONAL_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing_optional.append(pkg)

    if missing_required:
        err("Missing required packages:")
        for p in missing_required:
            info(f"  • {p}")
        print(f"\n  Run:  {B}pip install {' '.join(missing_required)}{RS}\n")
        sys.exit(1)

    if missing_optional:
        warn("Google Sheets upload packages not installed (optional):")
        for p in missing_optional:
            info(f"  • {p}")
        info(f"  Run:  pip install {' '.join(missing_optional)}  to enable auto-upload")

    return len(missing_optional) == 0


# ── config checker / first-time setup ────────────────────────────────────────

def check_config():
    from config import (
        GARMIN_EMAIL, GARMIN_PASSWORD,
        GOOGLE_SHEET_ID, SHORT_APPROACH_THRESHOLD_YARDS
    )

    issues = []
    if GARMIN_EMAIL == "your@email.com" and not os.environ.get("EMAIL"):
        issues.append("GARMIN_EMAIL not set")
    if GARMIN_PASSWORD == "yourpassword" and not os.environ.get("PASSWORD"):
        issues.append("GARMIN_PASSWORD not set (will prompt at runtime — that's fine)")

    if issues:
        warn("config.py has defaults — you'll be prompted for credentials when needed.")

    sheets_ready = GOOGLE_SHEET_ID and GOOGLE_SHEET_ID != "YOUR_SHEET_ID_HERE"
    if not sheets_ready:
        warn("GOOGLE_SHEET_ID not set — Google Sheets upload will be skipped")

    creds_file = ROOT / "credentials.json"
    if sheets_ready and not creds_file.exists():
        warn("credentials.json not found — Google Sheets upload will be skipped")
        sheets_ready = False

    return sheets_ready


# ── round selector ────────────────────────────────────────────────────────────

def choose_rounds(export_path: str) -> str:
    """
    After fetching, let user pick which rounds to process.
    Returns path to a (possibly filtered) JSON file.
    """
    with open(export_path, encoding="utf-8") as f:
        rounds = json.load(f)

    if len(rounds) == 1:
        ok(f"1 round loaded: {rounds[0].get('startTimeLocal','')[:10]}  "
           f"{rounds[0].get('activityName','')}")
        return export_path

    print(f"\n  {len(rounds)} round(s) available:\n")
    for i, r in enumerate(rounds):
        date_str = str(r.get("startTimeLocal") or "")[:10]
        name     = r.get("activityName") or f"Activity {r.get('activityId')}"
        print(f"    [{i+1:>2}]  {date_str}  {name}")

    print(f"\n    [ A]  Process ALL rounds")
    choice = input("\n  Enter number(s) to process (e.g. 1  or  1,3,5)  or A for all: ").strip()

    if choice.upper() == "A" or choice == "":
        return export_path

    indices = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(rounds):
                indices.append(idx)

    if not indices:
        warn("No valid selection — processing all rounds")
        return export_path

    selected = [rounds[i] for i in indices]
    filtered_path = export_path.replace(".json", "-selected.json")
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, indent=2)

    ok(f"Selected {len(selected)} round(s)")
    return filtered_path


# ── pipeline steps ────────────────────────────────────────────────────────────

def run_fetch(fetch_mode: str, last_n: int = None) -> str:
    """Run garmin_fetch.py and return path to output JSON."""
    import garmin_fetch

    if fetch_mode == "last":
        sys.argv = ["garmin_fetch.py", "--last", str(last_n)]
    else:
        sys.argv = ["garmin_fetch.py"]

    output = garmin_fetch.main()
    return output or f"{ROOT}/data/golf-export.json"


def run_parse(json_path: str) -> str:
    import parse_shots
    from config import SHOTS_CSV
    parse_shots.main(json_path, SHOTS_CSV)
    return SHOTS_CSV


def run_sg(shots_csv: str, profile: str = "tour"):
    import strokes_gained
    from config import SG_SHOTS_CSV, SG_SUMMARY_CSV
    strokes_gained.main(shots_csv, SG_SHOTS_CSV, SG_SUMMARY_CSV, profile=profile)
    return SG_SHOTS_CSV, SG_SUMMARY_CSV


def run_scorecard(shots_csv: str, sg_shots_csv: str):
    import format_scorecard
    from config import SCORECARD_CSV
    format_scorecard.main(shots_csv, sg_shots_csv, SCORECARD_CSV)
    return SCORECARD_CSV


def run_upload():
    import upload_to_sheets
    upload_to_sheets.main()


def print_summary():
    """Print a formatted summary of the SG results."""
    import csv
    from config import SG_SUMMARY_CSV, SCORECARD_CSV

    if not os.path.exists(SG_SUMMARY_CSV):
        return

    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        rounds = list(csv.DictReader(f))

    if not rounds:
        return

    print(f"\n{B}{'─'*62}{RS}")
    print(f"{B}  STROKES GAINED SUMMARY{RS}")
    print(f"{B}{'─'*62}{RS}")

    for r in rounds:
        def fmt(val):
            try:
                v = float(val)
                colour = G if v >= 0 else R
                return f"{colour}{v:+.2f}{RS}"
            except (ValueError, TypeError):
                return "  —  "

        print(f"\n  {B}{r['round_date']}  {r['course_name']}{RS}")
        print(f"  {'SG Total:':22s} {fmt(r['sg_total'])}")
        print(f"  {'SG Drives:':22s} {fmt(r['sg_drives'])}")
        print(f"  {'SG Long Approach:':22s} {fmt(r['sg_long_approach'])}")
        print(f"  {'SG Short Approach:':22s} {fmt(r['sg_short_approach'])}")
        print(f"  {'SG Putting:':22s} {fmt(r['sg_putting'])}")

    # Per-hole scorecard snapshot (last round only)
    if os.path.exists(SCORECARD_CSV):
        last_round_id = rounds[-1]["round_id"]
        with open(SCORECARD_CSV, newline="", encoding="utf-8") as f:
            holes = [row for row in csv.DictReader(f) if row["round_id"] == last_round_id]

        if holes:
            print(f"\n  {'─'*60}")
            print(f"  {B}HOLE-BY-HOLE  (most recent round){RS}")
            print(f"  {'─'*60}")
            hdr = f"  {'H':>2}  {'Par':>3}  {'Str':>3}  {'FW':<7}  {'GIR':<4}  {'App':>3}  {'Chip':>4}  {'Putt':>4}  {'SG':>7}"
            print(f"{B}{hdr}{RS}")
            for h in holes:
                sg = float(h["sg_hole_total"]) if h["sg_hole_total"] else 0
                sg_col = G if sg >= 0 else R
                print(f"  {h['hole_number']:>2}  {h['par']:>3}  {h['strokes']:>3}  "
                      f"{h['fairway']:<7}  {h['gir']:<4}  {h['approach_shots']:>3}  "
                      f"{h['chips']:>4}  {h['putts']:>4}  {sg_col}{sg:>+7.3f}{RS}")

    print(f"\n{B}{'─'*62}{RS}\n")


# ── main interactive flow ─────────────────────────────────────────────────────

def main():
    banner()

    # 1. Dependency check
    sheets_available = check_dependencies()
    sheets_ready     = check_config()
    sheets_enabled   = sheets_available and sheets_ready

    # 2. Ask what to do
    print(f"  {B}What would you like to do?{RS}\n")
    print(f"    {B}[1]{RS}  Fetch latest round from Garmin + run full pipeline")
    print(f"    {B}[2]{RS}  Fetch last N rounds from Garmin + run full pipeline")
    print(f"    {B}[3]{RS}  Fetch ALL rounds from Garmin + run full pipeline")
    print(f"    {B}[4]{RS}  Re-run pipeline on already-downloaded data  (skip fetch)")
    print(f"    {B}[5]{RS}  Run demo with synthetic data  (no Garmin account needed)")
    print(f"    {B}[Q]{RS}  Quit")

    choice = input("\n  Choice: ").strip().upper()

    if choice == "Q":
        sys.exit(0)

    os.makedirs(f"{ROOT}/data", exist_ok=True)

    # ── fetch ──────────────────────────────────────────────────────────────
    if choice in ("1", "2", "3"):
        step(1, "Fetch from Garmin Connect")

        if choice == "1":
            last_n = 1
        elif choice == "2":
            last_n = int(input("  How many recent rounds? ").strip() or "5")
        else:
            last_n = None

        sys.argv = ["garmin_fetch.py"] + (["--last", str(last_n)] if last_n else [])
        import garmin_fetch
        export_path = garmin_fetch.main() or f"{ROOT}/data/golf-export.json"

    elif choice == "4":
        step(1, "Using existing data")
        export_path = f"{ROOT}/data/golf-export.json"
        if not os.path.exists(export_path):
            err(f"No existing data found at {export_path}")
            info("Run option 1/2/3 first to fetch from Garmin")
            sys.exit(1)
        ok(f"Using: {export_path}")

    elif choice == "5":
        step(1, "Generating demo data")
        import run_pipeline
        demo_path = f"{ROOT}/data/demo-round.json"
        import json as _json
        with open(demo_path, "w") as f:
            _json.dump(run_pipeline.DEMO_ROUND, f, indent=2)
        export_path = demo_path
        ok("Demo round generated")

    else:
        err("Invalid choice")
        sys.exit(1)

    # ── round selection (if multiple rounds fetched) ───────────────────────
    if choice in ("2", "3"):
        export_path = choose_rounds(export_path)

    # ── benchmark profile selection ────────────────────────────────────────
    from benchmarks import PROFILE_LABELS
    print(f"\n  {B}Benchmark — compare yourself against:{RS}\n")
    print(f"    {B}[1]{RS}  Tour Pro   (PGA Tour — Broadie / ShotLink data)")
    print(f"    {B}[2]{RS}  Scratch    (0 handicap)")
    print(f"    {B}[3]{RS}  10 Handicap")
    print(f"    {B}[4]{RS}  Bogey      (18 handicap — typical club golfer)")
    profile_choice = input("\n  Choice [default: 1]: ").strip() or "1"
    profile = {"1": "tour", "2": "scratch", "3": "10", "4": "bogey"}.get(profile_choice, "tour")
    ok(f"Benchmark: {PROFILE_LABELS[profile]}")

    # ── parse ──────────────────────────────────────────────────────────────
    step(2, "Parse shots → CSV")
    shots_csv = run_parse(export_path)
    ok(f"Written: {shots_csv}")

    # ── strokes gained ─────────────────────────────────────────────────────
    step(3, "Calculate Strokes Gained")
    sg_shots_csv, sg_summary_csv = run_sg(shots_csv, profile=profile)
    ok(f"Shot detail: {sg_shots_csv}")
    ok(f"Round summary: {sg_summary_csv}")

    # ── scorecard format ───────────────────────────────────────────────────
    step(4, "Format scorecard")
    scorecard_csv = run_scorecard(shots_csv, sg_shots_csv)
    ok(f"Written: {scorecard_csv}")

    # ── Google Sheets upload ───────────────────────────────────────────────
    step(5, "Upload to Google Sheets")
    if sheets_enabled:
        try:
            run_upload()
            ok("Uploaded successfully")
        except Exception as e:
            warn(f"Upload failed: {e}")
    else:
        reasons = []
        if not sheets_available:
            reasons.append("google-api packages not installed")
        if not sheets_ready:
            reasons.append("GOOGLE_SHEET_ID / credentials.json not configured")
        warn("Skipped — " + "; ".join(reasons))
        info("See README.md → Google Sheets section to enable")

    # ── summary ────────────────────────────────────────────────────────────
    print_summary()

    ok("All output files:")
    from config import SHOTS_CSV, SG_SHOTS_CSV, SG_SUMMARY_CSV, SCORECARD_CSV
    for path in [SHOTS_CSV, SG_SHOTS_CSV, SG_SUMMARY_CSV, SCORECARD_CSV]:
        exists = G + "✓" + RS if os.path.exists(path) else R + "✗" + RS
        print(f"    {exists}  {path}")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {Y}Cancelled.{RS}\n")
        sys.exit(0)
