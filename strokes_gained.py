"""
strokes_gained.py — Step 3
══════════════════════════
Reads shots.csv and calculates strokes gained (SG) for every shot using
Mark Broadie's PGA Tour ShotLink benchmark table (Every Shot Counts, 2014).

Usage
─────
    python strokes_gained.py <shots.csv> <sg_shots.csv> <sg_summary.csv>

    # Default paths from config.py:
    python strokes_gained.py

Output A — sg_shots.csv  (one row per shot, everything from shots.csv plus):
    benchmark_start     expected strokes to hole from start position
    benchmark_end       expected strokes to hole from end position (0 if holed)
    sg                  strokes gained on this shot
    sg_category         drives | long_approach | short_approach | putting

Output B — sg_summary.csv  (one row per round):
    round_id, round_date, course_name,
    sg_total, sg_drives, sg_long_approach, sg_short_approach, sg_putting

═══════════════════════════════════════════════════════════════════════════════
BENCHMARK TABLE
───────────────
Values = average PGA Tour strokes to hole out.
Source: Broadie (2014), Table 5.2, Every Shot Counts.
Columns: distance (yards), tee, fairway, rough, sand, recovery, green (putting)

Off-green distances are in yards to the hole.
Putting distances are in feet to the hole (converted internally).
═══════════════════════════════════════════════════════════════════════════════
"""

import csv
import sys
import os
import bisect
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (DATA_DIR, SHOTS_CSV, SG_SHOTS_CSV, SG_SUMMARY_CSV,
                    SHORT_APPROACH_THRESHOLD_YARDS, EXCLUDE_ZERO_SG, BENCHMARK_PROFILE)
from benchmarks import expected_strokes, AVAILABLE_PROFILES


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK TABLES — see benchmarks.py
# expected_strokes() and get_profile() are imported from benchmarks.py
# ══════════════════════════════════════════════════════════════════════════════


def categorise_shot(start_lie: str, start_dist: float, threshold: float,
                    shot_type: str = "") -> str:
    """
    Assign shot to one of four SG categories.

    drives          — tee shots (shot_type==TEE) on par-4/5, start_dist > threshold
    long_approach   — non-tee shot starting beyond threshold yards
    short_approach  — non-tee shot starting within threshold yards, not on green
    putting         — shot starting on the green (shot_type==PUTT)
    """
    shot_type = (shot_type or "").upper()
    if shot_type == "PUTT" or start_lie == "green":
        return "putting"
    if shot_type == "TEE" or start_lie == "tee":
        return "drives" if start_dist is not None and start_dist > threshold else "short_approach"
    if start_dist is not None and start_dist > threshold:
        return "long_approach"
    return "short_approach"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

SG_SHOT_FIELDS = [
    "round_id", "round_date", "course_name",
    "hole_number", "par", "hole_yards", "hole_handicap",
    "shot_number", "club", "shot_type",
    "start_lie", "start_dist_yards",
    "end_lie",   "end_dist_yards",
    "penalty",
    "benchmark_start", "benchmark_end",
    "sg", "sg_category",
]

SG_SUMMARY_FIELDS = [
    "round_id", "round_date", "course_name",
    "benchmark_profile",
    "shots_counted",
    # Total  (shots = valid SG shots; shots_all = includes zero-excluded shots)
    "sg_total",            "sg_total_mean_per_shot",   "sg_total_median_per_shot",   "sg_total_shots",   "sg_total_shots_all",
    # Drives
    "sg_drives",           "sg_drives_mean_per_shot",  "sg_drives_median_per_shot",  "sg_drives_shots",  "sg_drives_shots_all",
    # Long approach
    "sg_long_approach",    "sg_long_approach_mean_per_shot",   "sg_long_approach_median_per_shot",   "sg_long_approach_shots",   "sg_long_approach_shots_all",
    # Short approach
    "sg_short_approach",   "sg_short_approach_mean_per_shot",  "sg_short_approach_median_per_shot",  "sg_short_approach_shots",  "sg_short_approach_shots_all",
    # Putting
    "sg_putting",          "sg_putting_mean_per_shot", "sg_putting_median_per_shot", "sg_putting_shots", "sg_putting_shots_all",
]


def _safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def compute_sg(shots_csv: str, sg_shots_csv: str, sg_summary_csv: str,
               threshold: float = SHORT_APPROACH_THRESHOLD_YARDS,
               profile: str = BENCHMARK_PROFILE):

    os.makedirs(os.path.dirname(sg_shots_csv) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(sg_summary_csv) or ".", exist_ok=True)

    sg_shot_rows = []
    skipped = 0

    print(f"Reading: {shots_csv}")
    print(f"Benchmark profile: {profile}")
    with open(shots_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            start_lie  = row.get("start_lie", "unknown").strip().lower()
            end_lie    = row.get("end_lie",   "unknown").strip().lower()
            start_dist = _safe_float(row.get("start_dist_yards"))
            end_dist   = _safe_float(row.get("end_dist_yards"))

            # Skip shots where we lack distance data
            if start_dist is None:
                skipped += 1
                row["benchmark_start"] = ""
                row["benchmark_end"]   = ""
                row["sg"]              = ""
                row["sg_category"]     = "unknown"
                sg_shot_rows.append(row)
                continue

            # Handle holed shots
            if end_lie == "hole" or end_dist == 0.0:
                end_dist = 0.0
                end_lie  = "hole"

            bm_start = expected_strokes(start_lie, start_dist, profile)
            bm_end   = expected_strokes(end_lie,   end_dist if end_dist is not None else 0.0, profile)

            if bm_start is None or bm_end is None:
                skipped += 1
                row["benchmark_start"] = bm_start if bm_start is not None else ""
                row["benchmark_end"]   = bm_end   if bm_end   is not None else ""
                row["sg"]              = ""
                row["sg_category"]     = "unknown"
                sg_shot_rows.append(row)
                continue

            # SG = benchmark_start − 1 (for the stroke taken) − benchmark_end
            sg_val = round(bm_start - 1 - bm_end, 4)
            category = categorise_shot(start_lie, start_dist, threshold, row.get('shot_type', ''))

            # Exclude exact-zero SG values — these almost always reflect bad/missing GPS
            # data (start and end distances identical) rather than a genuinely average shot.
            if EXCLUDE_ZERO_SG and sg_val == 0.0:
                skipped += 1
                row["benchmark_start"] = bm_start
                row["benchmark_end"]   = bm_end
                row["sg"]              = ""
                row["sg_category"]     = category
                sg_shot_rows.append(row)
                continue

            row["benchmark_start"] = bm_start
            row["benchmark_end"]   = bm_end
            row["sg"]              = sg_val
            row["sg_category"]     = category
            sg_shot_rows.append(row)

    # Write per-shot file
    with open(sg_shots_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SHOT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sg_shot_rows)
    print(f"Written: {sg_shots_csv}  ({len(sg_shot_rows)} shots, {skipped} skipped)")

    # ── Aggregate per round ──────────────────────────────────────────────────
    from collections import defaultdict
    import statistics

    CATS = ("drives", "long_approach", "short_approach", "putting")

    # Collect individual SG values per round per category for mean/median
    # Also track total shot counts including zero-excluded shots (for estimated impact)
    round_meta:      dict[str, dict]             = {}
    round_values:    dict[str, dict[str, list]]  = {}
    round_shots_all: dict[str, dict[str, int]]   = {}  # includes zero-excluded

    for row in sg_shot_rows:
        rid = row["round_id"]
        if rid not in round_meta:
            round_meta[rid] = {
                "round_id":          rid,
                "round_date":        row["round_date"],
                "course_name":       row["course_name"],
                "benchmark_profile": profile,
            }
            round_values[rid]    = {cat: [] for cat in CATS}
            round_values[rid]["total"] = []
            round_shots_all[rid] = {cat: 0 for cat in CATS}
            round_shots_all[rid]["total"] = 0

        cat = row.get("sg_category", "unknown")
        # Count every categorised shot regardless of whether SG is valid
        if cat in CATS:
            round_shots_all[rid][cat]    += 1
            round_shots_all[rid]["total"] += 1

        sg_val = _safe_float(row.get("sg"))
        if sg_val is None:
            continue

        round_values[rid]["total"].append(sg_val)
        if cat in CATS:
            round_values[rid][cat].append(sg_val)

    def _median(vals):
        return round(statistics.median(vals), 4) if vals else ""

    def _mean(vals):
        return round(statistics.mean(vals), 4) if vals else ""

    # Build summary rows
    rounds = {}
    for rid, meta in round_meta.items():
        v = round_values[rid]
        row_out = dict(meta)

        for cat, key in [("total", "sg_total"), ("drives", "sg_drives"),
                         ("long_approach", "sg_long_approach"),
                         ("short_approach", "sg_short_approach"),
                         ("putting", "sg_putting")]:
            vals = v[cat]
            row_out[key]                      = round(sum(vals), 4) if vals else 0.0
            row_out[f"{key}_mean_per_shot"]   = _mean(vals)
            row_out[f"{key}_median_per_shot"] = _median(vals)
            row_out[f"{key}_shots"]           = len(vals)
            row_out[f"{key}_shots_all"]       = round_shots_all[rid][cat]

        row_out["shots_counted"] = len(v["total"])
        rounds[rid] = row_out

    with open(sg_summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rounds.values())
    print(f"Written: {sg_summary_csv}  ({len(rounds)} round(s))")

    # Print summary to console
    def _fmt(v):
        return f"{v:+.3f}" if isinstance(v, float) else str(v)

    for r in rounds.values():
        print(f"\n  ── {r['round_date']} | {r['course_name']} ({r['benchmark_profile']}) ──")
        print(f"  {'Category':<16}  {'Total':>7}  {'Shots':>5}  {'Mean/shot':>10}  {'Median/shot':>12}")
        print(f"  {'-'*56}")
        for label, key in [
            ("Total",          "sg_total"),
            ("Drives",         "sg_drives"),
            ("Long Approach",  "sg_long_approach"),
            ("Short Approach", "sg_short_approach"),
            ("Putting",        "sg_putting"),
        ]:
            total  = r[key]
            shots  = r[f"{key}_shots"]
            mean   = r[f"{key}_mean_per_shot"]
            median = r[f"{key}_median_per_shot"]
            print(f"  {label:<16}  {total:>+7.2f}  {shots:>5}  "
                  f"{_fmt(mean):>10}  {_fmt(median):>12}")



def main(shots_csv: str = None, sg_shots_csv: str = None, sg_summary_csv: str = None,
         profile: str = None):
    """
    Run SG calculations for all four benchmark profiles and write combined results.
    sg_shots_csv stores the last-run profile's per-shot data.
    sg_summary_csv accumulates rows for ALL profiles (keyed by round_id + profile).
    """
    if shots_csv    is None: shots_csv    = sys.argv[1] if len(sys.argv) > 1 else SHOTS_CSV
    if sg_shots_csv is None: sg_shots_csv = sys.argv[2] if len(sys.argv) > 2 else SG_SHOTS_CSV
    if sg_summary_csv is None: sg_summary_csv = sys.argv[3] if len(sys.argv) > 3 else SG_SUMMARY_CSV

    # If a specific profile was requested (e.g. from run.py menu), run only that one
    # Otherwise run all four and combine
    if profile is None:
        for arg in sys.argv:
            if arg.startswith('--profile='):
                profile = arg.split('=', 1)[1]
                break

    profiles_to_run = AVAILABLE_PROFILES if profile is None else [profile]

    # Load all existing summary rows so we can merge without duplicating
    existing_rows = []
    if os.path.exists(sg_summary_csv):
        with open(sg_summary_csv, newline="", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))
    existing_keys = {(r["round_id"], r["benchmark_profile"]) for r in existing_rows}

    new_summary_rows = []
    for p in profiles_to_run:
        print(f"\n── Profile: {p} ──")
        # compute_sg writes sg_shots_csv for this profile; we capture summary rows
        compute_sg(shots_csv, sg_shots_csv, sg_summary_csv, profile=p)
        # Read the just-written summary and collect rows not already in existing
        with open(sg_summary_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["round_id"], row["benchmark_profile"])
                if key not in existing_keys:
                    new_summary_rows.append(row)
                    existing_keys.add(key)

    # Write merged summary (existing + new)
    all_rows = existing_rows + new_summary_rows
    # Remove dupes that might exist from old single-profile runs
    seen = set()
    deduped = []
    for row in all_rows:
        key = (row["round_id"], row["benchmark_profile"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    with open(sg_summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)
    print(f"\nSummary: {len(deduped)} round×profile rows in {sg_summary_csv}")


if __name__ == "__main__":
    main()
