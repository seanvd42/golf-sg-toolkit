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
    "sg_total",
    "sg_drives",
    "sg_long_approach",
    "sg_short_approach",
    "sg_putting",
    "shots_counted",
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

    rounds: dict[str, dict] = {}
    for row in sg_shot_rows:
        rid = row["round_id"]
        if rid not in rounds:
            rounds[rid] = {
                "round_id":    rid,
                "round_date":  row["round_date"],
                "course_name": row["course_name"],
                "benchmark_profile": profile,
                "sg_total":        0.0,
                "sg_drives":       0.0,
                "sg_long_approach":  0.0,
                "sg_short_approach": 0.0,
                "sg_putting":      0.0,
                "shots_counted":   0,
            }

        sg_val = _safe_float(row.get("sg"))
        if sg_val is None:
            continue

        cat = row.get("sg_category", "unknown")
        rounds[rid]["sg_total"] = round(rounds[rid]["sg_total"] + sg_val, 4)
        rounds[rid]["shots_counted"] += 1

        if cat == "drives":
            rounds[rid]["sg_drives"] = round(rounds[rid]["sg_drives"] + sg_val, 4)
        elif cat == "long_approach":
            rounds[rid]["sg_long_approach"] = round(rounds[rid]["sg_long_approach"] + sg_val, 4)
        elif cat == "short_approach":
            rounds[rid]["sg_short_approach"] = round(rounds[rid]["sg_short_approach"] + sg_val, 4)
        elif cat == "putting":
            rounds[rid]["sg_putting"] = round(rounds[rid]["sg_putting"] + sg_val, 4)

    with open(sg_summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SG_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rounds.values())
    print(f"Written: {sg_summary_csv}  ({len(rounds)} round(s))")

    # Print summary to console
    for r in rounds.values():
        print(f"\n  ── {r['round_date']} | {r['course_name']} ──")
        print(f"     SG Total:          {r['sg_total']:+.2f}")
        print(f"     SG Drives:         {r['sg_drives']:+.2f}")
        print(f"     SG Long Approach:  {r['sg_long_approach']:+.2f}")
        print(f"     SG Short Approach: {r['sg_short_approach']:+.2f}")
        print(f"     SG Putting:        {r['sg_putting']:+.2f}")


def main(shots_csv: str = None, sg_shots_csv: str = None, sg_summary_csv: str = None,
         profile: str = None):
    if shots_csv is None:
        shots_csv = sys.argv[1] if len(sys.argv) > 1 else SHOTS_CSV
    if sg_shots_csv is None:
        sg_shots_csv = sys.argv[2] if len(sys.argv) > 2 else SG_SHOTS_CSV
    if sg_summary_csv is None:
        sg_summary_csv = sys.argv[3] if len(sys.argv) > 3 else SG_SUMMARY_CSV
    if profile is None:
        # Allow --profile argument from command line
        for i, arg in enumerate(sys.argv):
            if arg == '--profile' and i + 1 < len(sys.argv):
                profile = sys.argv[i + 1]
                break
        else:
            profile = BENCHMARK_PROFILE
    compute_sg(shots_csv, sg_shots_csv, sg_summary_csv, profile=profile)


if __name__ == "__main__":
    main()
