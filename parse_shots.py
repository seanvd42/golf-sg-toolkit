"""
parse_shots.py — Step 2
═══════════════════════
Parse the JSON from garmin_fetch.py into a flat CSV where every row is one shot.

Real Garmin API structure (as of 2025/26):
─────────────────────────────────────────
round["scorecard"]
  ["scorecardDetails"][0]["scorecard"]
    ["holes"][i]  → strokes, penalties, putts, fairwayShotOutcome, pinPositionLat/Lon
  ["courseSnapshots"][0]
    ["holePars"]         → e.g. "443535444434444534" (one digit per hole)
    ["tees"][i]["holeHandicaps"]  → two digits per hole e.g. "090717..."

round["shots"]["holes"][i]
  ["holeNumber"]
  ["shots"][j]
    ["shotOrder"]             → 1-indexed
    ["shotType"]              → TEE | APPROACH | CHIP | PUTT | RECOVERY | UNKNOWN
    ["clubId"]                → numeric ID
    ["startLoc"]["lat/lon/lie"]   → lat/lon integer degrees×1e7; lie = TeeBox|Rough|…
    ["endLoc"]["lat/lon/lie"]
    ["meters"]                → shot distance (NOT distance to hole)

Distance-to-hole is computed via haversine from each loc to pinPositionLat/Lon.
"""

import json, csv, sys, math, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR, SHOTS_CSV, LIE_ALIAS

HOLE_THRESHOLD_YARDS = 3.0   # last putt within this → treat as holed

# ── coordinate helpers ────────────────────────────────────────────────────────

def _ll(raw):
    return raw / 1e7

def haversine_yards(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2-lat1)/2)**2
         + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return round(2*R*math.asin(math.sqrt(a))*1.09361, 1)

# ── lie normalisation ─────────────────────────────────────────────────────────

_LIE_MAP = {
    "teebox": "tee", "tee": "tee",
    "fairway": "fairway",
    "rough": "rough",
    "bunker": "sand", "sand": "sand",
    "green": "green",
    "fringe": "rough",
    "recovery": "recovery",
    "unknown": "rough",
    "water": "recovery", "ob": "rough",
}

def normalise_lie(raw):
    if not raw:
        return "unknown"
    key = raw.strip().lower()
    return _LIE_MAP.get(key) or LIE_ALIAS.get(key) or key

# ── scorecard metadata ────────────────────────────────────────────────────────

def extract_scorecard_meta(round_data):
    sc_blob  = round_data.get("scorecard") or {}
    details  = sc_blob.get("scorecardDetails") or []
    inner_sc = (details[0].get("scorecard") or {}) if details else {}
    snap     = (sc_blob.get("courseSnapshots") or [{}])[0]

    course_name = (snap.get("name") or inner_sc.get("courseName")
                   or round_data.get("activityName", "Unknown Course"))
    round_date  = str(inner_sc.get("startTime") or round_data.get("startTimeLocal",""))[:10]

    # Par per hole: "443535..." → [4,4,3,5,3,5,…]
    pars_str  = snap.get("holePars", "")
    hole_pars = [int(c) for c in pars_str] if pars_str else []

    # Handicap per hole: "090717..." → [9,7,17,…]
    tee_name = inner_sc.get("teeBox", "")
    tees = snap.get("tees", [])
    tee  = next((t for t in tees if t.get("name","").lower() == tee_name.lower()), None)
    if not tee and tees:
        tee = tees[0]
    hcap_str  = (tee or {}).get("holeHandicaps", "")
    hole_hcaps = [int(hcap_str[i:i+2]) for i in range(0, len(hcap_str), 2)] if hcap_str else []

    hole_metas = {}
    for i, h in enumerate(inner_sc.get("holes", [])):
        n = h.get("number") or h.get("holeNumber") or (i+1)
        hole_metas[n] = {
            "hole_number":   n,
            "par":           hole_pars[i]  if i < len(hole_pars)  else 4,
            "hole_handicap": hole_hcaps[i] if i < len(hole_hcaps) else 0,
            "hole_yards":    0,   # not in this API response
            "strokes":       h.get("strokes", 0),
            "penalties":     h.get("penalties", 0),
            "putts":         h.get("putts", 0),
            "fairway":       h.get("fairwayShotOutcome", ""),
            "pin_lat":       _ll(h["pinPositionLat"]) if h.get("pinPositionLat") else None,
            "pin_lon":       _ll(h["pinPositionLon"]) if h.get("pinPositionLon") else None,
        }

    return course_name, round_date, hole_metas

# ── per-hole shot parser ──────────────────────────────────────────────────────

def _resolve_club(club_id, club_map):
    """Return club name from map if available, else numeric ID string, else empty."""
    if not club_id:
        return ""
    if club_map:
        name = club_map.get(int(club_id))
        if name:
            return name
    return str(club_id)


def parse_shots_for_hole(hole_data, meta, club_map=None):
    shots_raw = sorted(hole_data.get("shots", []), key=lambda s: s.get("shotOrder", 0))
    pin_lat   = meta.get("pin_lat")
    pin_lon   = meta.get("pin_lon")
    n         = len(shots_raw)
    rows      = []

    for idx, s in enumerate(shots_raw):
        sl = s.get("startLoc", {})
        el = s.get("endLoc", {})

        start_lie = normalise_lie(sl.get("lie", ""))
        end_lie   = normalise_lie(el.get("lie", ""))

        start_dist = (haversine_yards(_ll(sl["lat"]), _ll(sl["lon"]), pin_lat, pin_lon)
                      if pin_lat is not None and sl.get("lat") is not None else None)
        end_dist   = (haversine_yards(_ll(el["lat"]), _ll(el["lon"]), pin_lat, pin_lon)
                      if pin_lat is not None and el.get("lat") is not None else None)

        # Last shot within HOLE_THRESHOLD_YARDS → treat as holed
        if idx == n-1 and end_dist is not None and end_dist <= HOLE_THRESHOLD_YARDS:
            end_dist = 0.0
            end_lie  = "hole"

        rows.append({
            "hole_number":      meta["hole_number"],
            "par":              meta["par"],
            "hole_yards":       meta["hole_yards"],
            "hole_handicap":    meta["hole_handicap"],
            "shot_number":      s.get("shotOrder", idx+1),
            "club":             _resolve_club(s.get("clubId"), club_map),
            "shot_type":        s.get("shotType", "UNKNOWN").upper(),
            "start_lie":        start_lie,
            "start_dist_yards": start_dist if start_dist is not None else "",
            "end_lie":          end_lie,
            "end_dist_yards":   end_dist   if end_dist   is not None else "",
            "penalty":          0,
        })

    # Apportion hole-level penalties to the last non-putt shot
    hp = meta.get("penalties", 0)
    if hp:
        non_putts = [r for r in rows if r["shot_type"] != "PUTT"]
        if non_putts:
            non_putts[-1]["penalty"] = hp

    return rows

# ── round parser ──────────────────────────────────────────────────────────────

def parse_round(round_data):
    activity_id               = round_data.get("activityId", "")
    course_name, round_date, hole_metas = extract_scorecard_meta(round_data)

    # Build clubId → name lookup from the clubs dict fetched by garmin_fetch.py
    clubs_raw = round_data.get("clubs") or {}
    # clubs is stored as {str(clubId): name} or {int: name}
    club_map  = {int(k): v for k, v in clubs_raw.items()} if isinstance(clubs_raw, dict) else {}

    all_rows = []
    for hd in (round_data.get("shots") or {}).get("holes", []):
        h_num = hd.get("holeNumber", 0)
        meta  = hole_metas.get(h_num, {
            "hole_number": h_num, "par": 4, "hole_yards": 0,
            "hole_handicap": 0, "penalties": 0, "pin_lat": None, "pin_lon": None,
        })
        for r in parse_shots_for_hole(hd, meta, club_map):
            r["round_id"]    = activity_id
            r["round_date"]  = round_date
            r["course_name"] = course_name
            all_rows.append(r)

    return all_rows

# ── CSV output ────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "round_id", "round_date", "course_name",
    "hole_number", "par", "hole_yards", "hole_handicap",
    "shot_number", "club", "shot_type",
    "start_lie", "start_dist_yards",
    "end_lie",   "end_dist_yards",
    "penalty",
]

def main(input_path=None, output_path=None):
    if input_path  is None:
        input_path  = sys.argv[1] if len(sys.argv) > 1 else f"{DATA_DIR}/golf-export.json"
    if output_path is None:
        output_path = sys.argv[2] if len(sys.argv) > 2 else SHOTS_CSV

    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Reading: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rounds   = data if isinstance(data, list) else [data]
    all_rows = []
    for rd in rounds:
        rows = parse_round(rd)
        all_rows.extend(rows)
        print(f"  Round {rd.get('activityId','?')} "
              f"({str(rd.get('startTimeLocal',''))[:10]}): {len(rows)} shots")

    print(f"\nTotal shots: {len(all_rows)}")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Written: {output_path}")

if __name__ == "__main__":
    main()
