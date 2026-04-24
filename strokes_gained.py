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
                    SHORT_APPROACH_THRESHOLD_YARDS, EXCLUDE_ZERO_SG)
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
    "sg_category",
    # One SG column per benchmark profile
    "sg_tour", "sg_scratch", "sg_10", "sg_bogey",
]


SG_SUMMARY_FIELDS = [
    "round_id", "round_date", "course_name",
    "benchmark_profile", "shots_counted",
    "sg_total",           "sg_total_mean_per_shot",          "sg_total_median_per_shot",          "sg_total_shots",          "sg_total_shots_all",
    "sg_drives",          "sg_drives_mean_per_shot",         "sg_drives_median_per_shot",         "sg_drives_shots",         "sg_drives_shots_all",
    "sg_long_approach",   "sg_long_approach_mean_per_shot",  "sg_long_approach_median_per_shot",  "sg_long_approach_shots",  "sg_long_approach_shots_all",
    "sg_short_approach",  "sg_short_approach_mean_per_shot", "sg_short_approach_median_per_shot", "sg_short_approach_shots", "sg_short_approach_shots_all",
    "sg_putting",         "sg_putting_mean_per_shot",        "sg_putting_median_per_shot",        "sg_putting_shots",        "sg_putting_shots_all",
]


def _safe_float(val):
    try:    return float(val)
    except: return None


def compute_sg(shots_csv: str, sg_shots_csv: str, sg_summary_csv: str,
               threshold: float = SHORT_APPROACH_THRESHOLD_YARDS,
               profile: str = "tour"):
    """
    Compute SG for all four benchmark profiles in one pass.
    sg_shots_csv gets one row per shot with sg_tour/sg_scratch/sg_10/sg_bogey columns.
    sg_summary_csv gets one row per round × profile (four rows per round).
    The `profile` argument is kept for compatibility but all profiles always run.
    """
    os.makedirs(os.path.dirname(sg_shots_csv) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(sg_summary_csv) or ".", exist_ok=True)

    sg_shot_rows = []
    skipped = 0

    print(f"Reading: {shots_csv}")
    print(f"Computing SG for all profiles: {AVAILABLE_PROFILES}")

    with open(shots_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            start_lie  = row.get("start_lie",  "unknown").strip().lower()
            end_lie    = row.get("end_lie",    "unknown").strip().lower()
            start_dist = _safe_float(row.get("start_dist_yards"))
            end_dist   = _safe_float(row.get("end_dist_yards"))

            # Category is the same regardless of profile
            category = categorise_shot(
                start_lie, start_dist, threshold, row.get("shot_type", "")
            ) if start_dist is not None else "unknown"
            row["sg_category"] = category

            if start_dist is None:
                skipped += 1
                for p in AVAILABLE_PROFILES:
                    row[f"sg_{p}"] = ""
                sg_shot_rows.append(row)
                continue

            # Handle holed shots
            if end_lie == "hole" or end_dist == 0.0:
                end_dist = 0.0
                end_lie  = "hole"

            # Compute SG for every profile
            for p in AVAILABLE_PROFILES:
                bm_start = expected_strokes(start_lie, start_dist, p)
                bm_end   = expected_strokes(end_lie, end_dist if end_dist is not None else 0.0, p)

                if bm_start is None or bm_end is None:
                    row[f"sg_{p}"] = ""
                    continue

                sg_val = round(bm_start - 1 - bm_end, 4)

                if EXCLUDE_ZERO_SG and sg_val == 0.0:
                    row[f"sg_{p}"] = ""
                else:
                    row[f"sg_{p}"] = sg_val

            sg_shot_rows.append(row)

    with open(sg_shots_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SHOT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sg_shot_rows)
    print(f"Written: {sg_shots_csv}  ({len(sg_shot_rows)} shots, {skipped} skipped)")

    # ── Aggregate per round × profile ────────────────────────────────────────
    from collections import defaultdict
    import statistics

    CATS = ("drives", "long_approach", "short_approach", "putting")

    # round × profile → {cat: [sg_values], cat_all: count_including_zeros}
    round_meta   = {}
    round_vals   = {}   # (rid, profile) → {cat: [valid_sg_vals]}
    round_all    = {}   # (rid, profile) → {cat: total_shot_count}

    for row in sg_shot_rows:
        rid = row["round_id"]
        cat = row.get("sg_category", "unknown")

        for p in AVAILABLE_PROFILES:
            key = (rid, p)
            if key not in round_meta:
                round_meta[key] = {
                    "round_id":          rid,
                    "round_date":        row["round_date"],
                    "course_name":       row["course_name"],
                    "benchmark_profile": p,
                }
                round_vals[key] = {c: [] for c in CATS}
                round_vals[key]["total"] = []
                round_all[key] = {c: 0 for c in CATS}
                round_all[key]["total"] = 0

            if cat in CATS:
                round_all[key][cat]    += 1
                round_all[key]["total"] += 1

            sg_val = _safe_float(row.get(f"sg_{p}"))
            if sg_val is not None:
                round_vals[key]["total"].append(sg_val)
                if cat in CATS:
                    round_vals[key][cat].append(sg_val)

    def _median(vals):
        return round(statistics.median(vals), 4) if vals else ""

    def _mean(vals):
        return round(statistics.mean(vals), 4) if vals else ""

    summary_rows = []
    for key, meta in round_meta.items():
        v   = round_vals[key]
        all_ = round_all[key]
        row_out = dict(meta)

        for cat, sg_key in [("total",         "sg_total"),
                             ("drives",        "sg_drives"),
                             ("long_approach",  "sg_long_approach"),
                             ("short_approach", "sg_short_approach"),
                             ("putting",        "sg_putting")]:
            vals = v[cat]
            row_out[sg_key]                        = round(sum(vals), 4) if vals else 0.0
            row_out[f"{sg_key}_mean_per_shot"]     = _mean(vals)
            row_out[f"{sg_key}_median_per_shot"]   = _median(vals)
            row_out[f"{sg_key}_shots"]             = len(vals)
            row_out[f"{sg_key}_shots_all"]         = all_[cat]

        row_out["shots_counted"] = len(v["total"])
        summary_rows.append(row_out)

    # ── Merge with existing summary (avoid duplicating round×profile rows) ────
    existing_rows = []
    if os.path.exists(sg_summary_csv):
        with open(sg_summary_csv, newline="", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    existing_keys = {(r["round_id"], r["benchmark_profile"]) for r in existing_rows}
    new_rows = [r for r in summary_rows
                if (r["round_id"], r["benchmark_profile"]) not in existing_keys]

    all_summary = existing_rows + new_rows
    # Deduplicate in case of overlap
    seen, deduped = set(), []
    for r in all_summary:
        k = (r["round_id"], r["benchmark_profile"])
        if k not in seen:
            seen.add(k)
            deduped.append(r)

    with open(sg_summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)
    print(f"Written: {sg_summary_csv}  ({len(deduped)} total round×profile rows)")

    # Console summary — one line per round, all four profiles
    def _fmt(v):
        return f"{v:+.3f}" if isinstance(v, float) else "   —  "

    # Group by round_id for compact display
    from collections import defaultdict as _dd
    by_round = _dd(dict)
    for key, meta in round_meta.items():
        rid = meta["round_id"]
        p   = meta["benchmark_profile"]
        by_round[rid]["date"]   = meta["round_date"]
        by_round[rid]["course"] = meta["course_name"]
        by_round[rid][p]        = round_vals[key]

    for rid, info in by_round.items():
        print(f"\n  {info['date']}  {info['course']}")
        print(f"  {'Benchmark':<10}  {'Drives':>8}  {'Long App':>9}  {'Short App':>10}  {'Putting':>9}  {'Total':>8}")
        print(f"  {'-'*62}")
        for p in ["tour","scratch","10","bogey"]:
            if p not in info: continue
            v = info[p]
            def sg(cat): return round(sum(v.get(cat,[])), 3)
            print(f"  {p:<10}  {sg('drives'):>+8.2f}  {sg('long_approach'):>+9.2f}"
                  f"  {sg('short_approach'):>+10.2f}  {sg('putting'):>+9.2f}  {sg('total'):>+8.2f}")


def main(shots_csv=None, sg_shots_csv=None, sg_summary_csv=None, profile=None):
    if shots_csv      is None: shots_csv      = sys.argv[1] if len(sys.argv) > 1 else SHOTS_CSV
    if sg_shots_csv   is None: sg_shots_csv   = sys.argv[2] if len(sys.argv) > 2 else SG_SHOTS_CSV
    if sg_summary_csv is None: sg_summary_csv = sys.argv[3] if len(sys.argv) > 3 else SG_SUMMARY_CSV
    compute_sg(shots_csv, sg_shots_csv, sg_summary_csv)


if __name__ == "__main__":
    main()
