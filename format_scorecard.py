"""
format_scorecard.py — Step 4
═════════════════════════════
Reads shots.csv (from parse_shots.py) and sg_shots.csv (from strokes_gained.py),
plus the original golf-export.json for ground-truth scorecard data, and produces
a per-hole scorecard CSV matching your tracking sheet layout.

The scorecard columns directly from Garmin (ground truth):
    strokes, putts, penalties, fairway (HIT/LEFT/RIGHT/SHORT/LONG → center/left/right/short/long)

The columns derived from the shot list:
    approach_shots, chips, gir, bgir, sg_*

Usage
─────
    python format_scorecard.py [shots.csv] [sg_shots.csv] [scorecard.csv]
    python format_scorecard.py                   # uses paths from config.py
"""

import csv, sys, os, json
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR, SHOTS_CSV, SG_SHOTS_CSV, SCORECARD_CSV, SHORT_APPROACH_THRESHOLD_YARDS

# ── helpers ───────────────────────────────────────────────────────────────────

def _fi(val, default=0):
    try:    return int(float(val))
    except: return default

def _ff(val):
    try:    return float(val)
    except: return None

# Garmin fairwayShotOutcome → your tracking column values
_FW_MAP = {
    "HIT":   "center",
    "LEFT":  "left",
    "RIGHT": "right",
    "SHORT": "short",
    "LONG":  "long",
    "":      "",
}

def map_fairway(outcome: str, par: int) -> str:
    if par == 3:
        return "N/A"
    return _FW_MAP.get(str(outcome).upper(), outcome.lower() if outcome else "")

# ── main ──────────────────────────────────────────────────────────────────────

SCORECARD_FIELDS = [
    "round_id", "round_date", "course_name",
    "hole_number", "par", "hole_yards", "hole_handicap",
    "strokes", "adj_strokes",
    "fairway", "gir", "bgir",
    "approach_shots", "chips", "putts", "penalties",
    "sg_hole_total", "sg_drives", "sg_long_approach", "sg_short_approach", "sg_putting",
]

def build_scorecard(shots_csv, sg_shots_csv, output_csv,
                    threshold=SHORT_APPROACH_THRESHOLD_YARDS):

    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)

    # ── Load SG shots (prefer over plain shots — has benchmark + sg) ──────────
    source = sg_shots_csv if os.path.exists(sg_shots_csv) else shots_csv
    print(f"Reading: {source}")

    # Group by (round_id, hole_number)
    holes = defaultdict(list)
    with open(source, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["round_id"], _fi(row["hole_number"]))
            holes[key].append(row)

    for key in holes:
        holes[key].sort(key=lambda r: _fi(r.get("shot_number", 0)))

    rows_out = []

    for (round_id, hole_num), shots in sorted(holes.items()):
        if not shots:
            continue

        first = shots[0]
        par           = _fi(first.get("par", 4))
        hole_yards    = _fi(first.get("hole_yards", 0))
        hole_handicap = _fi(first.get("hole_handicap", 0))
        round_date    = first.get("round_date", "")
        course_name   = first.get("course_name", "")

        # ── SG accumulation ───────────────────────────────────────────────────
        sg_total  = sg_drv = sg_long = sg_short = sg_putt = 0.0
        for s in shots:
            v   = _ff(s.get("sg"))
            cat = s.get("sg_category", "")
            if v is None:
                continue
            sg_total += v
            if   cat == "drives":        sg_drv   += v
            elif cat == "long_approach": sg_long  += v
            elif cat == "short_approach":sg_short += v
            elif cat == "putting":       sg_putt  += v

        # ── Shot category counts (from shot_type field) ───────────────────────
        # Use Garmin's own shot_type tags which are accurate:
        #   TEE, APPROACH, CHIP, PUTT, RECOVERY, UNKNOWN
        # "approach_shots" = TEE + APPROACH + RECOVERY + UNKNOWN (non-chip, non-putt)
        # "chips"          = CHIP shots
        # "putts"          = PUTT shots  (cross-check with scorecard putts)
        putts  = sum(1 for s in shots if s.get("shot_type") == "PUTT")
        chips  = sum(1 for s in shots if s.get("shot_type") == "CHIP")
        # For approaches: TEE + APPROACH + RECOVERY + UNKNOWN (anything before green, not chip)
        approach_shots = sum(1 for s in shots
                             if s.get("shot_type") in ("TEE", "APPROACH", "RECOVERY", "UNKNOWN"))

        # ── GIR / bGIR ────────────────────────────────────────────────────────
        # Find the shot number on which the ball first reaches the green
        shots_to_reach_green = None
        for s in shots:
            if s.get("end_lie") == "green" or s.get("shot_type") == "PUTT":
                shots_to_reach_green = _fi(s.get("shot_number", 0))
                break
        if shots_to_reach_green is None:
            shots_to_reach_green = len(shots)

        gir  = "Y" if shots_to_reach_green <= (par - 2) else "N"
        bgir = "Y" if shots_to_reach_green <= (par - 1) else "N"

        # ── Strokes & fairway from scorecard ground truth ─────────────────────
        # These were stored in the shot rows if available from the source file.
        # Fall back to counting shots in the CSV if not.
        strokes    = len(shots)
        adj_strokes = min(strokes, par + 2)

        # Fairway: stored on the TEE shot row via shot_type==TEE context,
        # but we don't carry it through shots CSV — use par check on approach count
        # Actually fairway is not in the shots CSV; we leave it blank here.
        # It IS available if we reload the original JSON — handled in main() below.
        fairway = ""

        rows_out.append({
            "round_id":          round_id,
            "round_date":        round_date,
            "course_name":       course_name,
            "hole_number":       hole_num,
            "par":               par,
            "hole_yards":        hole_yards,
            "hole_handicap":     hole_handicap,
            "strokes":           strokes,
            "adj_strokes":       adj_strokes,
            "fairway":           fairway,
            "gir":               gir,
            "bgir":              bgir,
            "approach_shots":    approach_shots,
            "chips":             chips,
            "putts":             putts,
            "penalties":         0,   # filled from scorecard below
            "sg_hole_total":     round(sg_total, 3),
            "sg_drives":         round(sg_drv,   3),
            "sg_long_approach":  round(sg_long,  3),
            "sg_short_approach": round(sg_short, 3),
            "sg_putting":        round(sg_putt,  3),
        })

    # ── Enrich with ground-truth scorecard data from JSON ─────────────────────
    json_path = f"{DATA_DIR}/golf-export.json"
    if os.path.exists(json_path):
        _enrich_from_json(rows_out, json_path)
    else:
        print(f"  ℹ️  {json_path} not found — strokes/putts/penalties/fairway from shot counts only")

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORECARD_FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Written: {output_csv}  ({len(rows_out)} hole rows)")


def _enrich_from_json(rows_out: list[dict], json_path: str):
    """
    Overwrite strokes, adj_strokes, putts, penalties, fairway with
    ground-truth values from the original Garmin JSON export.
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    rounds = data if isinstance(data, list) else [data]

    # Build lookup: (round_id_str, hole_num) → scorecard hole dict
    sc_lookup = {}
    for rd in rounds:
        rid = str(rd.get("activityId", ""))
        sc_blob  = rd.get("scorecard") or {}
        details  = sc_blob.get("scorecardDetails") or []
        inner_sc = (details[0].get("scorecard") or {}) if details else {}
        snap     = (sc_blob.get("courseSnapshots") or [{}])[0]
        pars_str = snap.get("holePars", "")
        hole_pars = [int(c) for c in pars_str] if pars_str else []

        for i, h in enumerate(inner_sc.get("holes", [])):
            h_num = h.get("number") or h.get("holeNumber") or (i+1)
            par   = hole_pars[i] if i < len(hole_pars) else 4
            sc_lookup[(rid, h_num)] = {
                "strokes":    h.get("strokes", 0),
                "putts":      h.get("putts", 0),
                "penalties":  h.get("penalties", 0),
                "fairway_raw": h.get("fairwayShotOutcome", ""),
                "par":        par,
            }

    for row in rows_out:
        key = (str(row["round_id"]), row["hole_number"])
        sc  = sc_lookup.get(key)
        if not sc:
            continue
        strokes     = sc["strokes"]
        adj_strokes = min(strokes, sc["par"] + 2)
        row["strokes"]     = strokes
        row["adj_strokes"] = adj_strokes
        row["putts"]       = sc["putts"]
        row["penalties"]   = sc["penalties"]
        row["fairway"]     = map_fairway(sc["fairway_raw"], sc["par"])

    print("  ✓  Enriched with ground-truth strokes/putts/penalties/fairway from JSON")


def main(shots_csv=None, sg_shots_csv=None, output_csv=None):
    if shots_csv    is None:
        shots_csv    = sys.argv[1] if len(sys.argv) > 1 else SHOTS_CSV
    if sg_shots_csv is None:
        sg_shots_csv = sys.argv[2] if len(sys.argv) > 2 else SG_SHOTS_CSV
    if output_csv   is None:
        output_csv   = sys.argv[3] if len(sys.argv) > 3 else SCORECARD_CSV
    build_scorecard(shots_csv, sg_shots_csv, output_csv)

if __name__ == "__main__":
    main()
