"""
benchmarks.py — Strokes-gained benchmark tables
════════════════════════════════════════════════
Four profiles comparing your shots against different player populations:

    "tour"    PGA Tour professionals
    "scratch" 0 handicap amateur
    "10"      10 handicap amateur
    "bogey"   18 handicap amateur  (aka "bogey golfer")

DATA SOURCES
────────────
Tour:    Mark Broadie, "Every Shot Counts" (2014).
         PGA Tour ShotLink data 2004-2012.

Amateur: No freely published equivalent to Broadie's tables exists.
         We use Tour as a base and apply additive deltas calibrated against:

         • Arccos/Pinpoint: 160 yd fairway → Tour 2.98, 15-hcp 3.92
           (published calibration point)
         • Shot Scope (published averages by handicap, ebook 2020):
           average putts per round — Tour ~28.5, scratch ~31, 10-hcp ~33,
           bogey ~35-36
         • Broadie (everyshotcounts.com Q&A): PGA Tour ≈ +4 world handicap;
           scratch ≈ 9 shots behind tour per round → ~0.5 shots/hole
         • General consensus from Arccos, Shot Scope, 18Birdies data:
           10-hcp ≈ 5 shots/round worse than scratch;
           bogey ≈ 9 shots/round worse than scratch (18 shots behind tour)

         The deltas below are graduated by distance and lie — the amateur
         penalty grows faster at long distances (driving gap) and is
         minimal at very short putts (everyone holes a 1-footer).

         These are reasoned estimates consistent with all published data.
         They are NOT from a proprietary database.

PROFILE SELECTION
─────────────────
Set in config.py:   BENCHMARK_PROFILE = "tour"   # or "scratch", "10", "bogey"
"""

import bisect, math

# ── interpolation helpers ─────────────────────────────────────────────────────

def _build(table):
    t = sorted(table, key=lambda x: x[0])
    return [r[0] for r in t], [r[1] for r in t]

def _interp(xs, ys, x):
    if x <= xs[0]:  return ys[0]
    if x >= xs[-1]: return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    t = (x - xs[i]) / (xs[i+1] - xs[i])
    return round(ys[i] + t * (ys[i+1] - ys[i]), 4)

# ── Tour baseline (Broadie, Every Shot Counts) ────────────────────────────────

_TOUR_RAW = {
    "tee": [
        (100,3.00),(125,3.09),(150,3.15),(175,3.23),(200,3.30),
        (225,3.39),(250,3.48),(275,3.58),(300,3.71),(325,3.84),
        (350,3.99),(375,4.11),(400,4.23),(425,4.35),(450,4.50),
        (475,4.63),(500,4.77),(525,4.89),(550,5.03),(575,5.18),(600,5.32),
    ],
    "fairway": [
        (5,2.10),(10,2.40),(15,2.52),(20,2.60),(25,2.66),
        (30,2.72),(40,2.78),(50,2.80),(60,2.81),(75,2.82),
        (100,2.80),(110,2.81),(120,2.85),(130,2.88),(140,2.93),
        (150,2.98),(160,3.03),(170,3.10),(180,3.17),(190,3.24),
        (200,3.32),(220,3.48),(240,3.62),(260,3.74),(280,3.86),
        (300,3.99),(350,4.23),(400,4.50),(450,4.77),(500,5.03),
    ],
    "rough": [
        (5,2.15),(10,2.47),(15,2.60),(20,2.68),(25,2.74),
        (30,2.80),(40,2.86),(50,2.90),(60,2.93),(75,2.96),
        (100,3.02),(120,3.07),(140,3.15),(160,3.26),(180,3.40),
        (200,3.55),(220,3.70),(250,3.89),(300,4.13),(350,4.37),(400,4.61),
    ],
    "sand": [
        (5,2.37),(10,2.52),(15,2.53),(20,2.56),(25,2.60),
        (30,2.68),(40,2.79),(50,2.89),(60,2.95),(75,3.01),
        (100,3.10),(120,3.17),(140,3.27),(160,3.40),(180,3.54),
        (200,3.69),(250,4.02),(300,4.30),(350,4.55),(400,4.80),
    ],
    "recovery": [
        (5,2.50),(10,2.70),(20,2.88),(30,3.00),(50,3.14),
        (75,3.24),(100,3.36),(150,3.62),(200,3.87),(250,4.07),
        (300,4.25),(400,4.63),(500,5.00),
    ],
    # Distance in FEET for putting
    "green": [
        (1,1.010),(2,1.028),(3,1.077),(4,1.148),(5,1.228),
        (6,1.318),(7,1.400),(8,1.476),(9,1.546),(10,1.608),
        (11,1.661),(12,1.704),(13,1.740),(14,1.770),(15,1.797),
        (16,1.820),(17,1.840),(18,1.859),(19,1.875),(20,1.890),
        (22,1.916),(25,1.949),(30,1.990),(36,2.020),
        (40,2.040),(50,2.090),(60,2.130),(75,2.190),(100,2.330),
    ],
}

# ── Amateur deltas: extra strokes vs Tour by (distance, lie) ─────────────────
# Format: (distance, scratch_delta, hcp10_delta, bogey_delta)
#
# Calibration anchors:
#   fairway 160 yd: scratch≈+0.47, hcp10≈+0.85, bogey18≈+1.31  (scaled from Arccos 15-hcp=+0.94)
#   putting 20 ft:  scratch≈+0.09, hcp10≈+0.40, bogey18≈+0.70  (from putts/round averages)
#   tee 350 yd:     scratch≈+0.50, hcp10≈+1.05, bogey18≈+1.80  (from scoring differentials)
#
# Key principle: the gap between benchmarks grows with distance and
# shrinks at very short range (< 5 ft puts, < 10 yd chips).

_DELTAS = {
    # (dist_yd, scratch, hcp10, bogey18)
    "tee": [
        (100, 0.10, 0.30, 0.55),
        (150, 0.14, 0.42, 0.75),
        (200, 0.20, 0.55, 1.00),
        (250, 0.28, 0.72, 1.30),
        (300, 0.38, 0.90, 1.60),
        (350, 0.50, 1.05, 1.80),
        (400, 0.58, 1.18, 2.00),
        (450, 0.65, 1.30, 2.18),
        (500, 0.72, 1.42, 2.35),
        (550, 0.78, 1.52, 2.50),
    ],
    "fairway": [
        (5,   0.04, 0.10, 0.18),
        (10,  0.05, 0.13, 0.24),
        (20,  0.06, 0.16, 0.30),
        (30,  0.07, 0.19, 0.36),
        (50,  0.09, 0.24, 0.45),
        (75,  0.12, 0.32, 0.60),
        (100, 0.16, 0.43, 0.80),
        (120, 0.21, 0.54, 1.00),
        (140, 0.28, 0.67, 1.17),
        (160, 0.36, 0.85, 1.40),  # anchor: hcp10≈+0.85
        (180, 0.42, 0.96, 1.58),
        (200, 0.48, 1.08, 1.76),
        (220, 0.54, 1.18, 1.92),
        (250, 0.62, 1.32, 2.12),
        (300, 0.72, 1.50, 2.40),
        (400, 0.88, 1.80, 2.85),
    ],
    "rough": [
        (5,   0.05, 0.14, 0.25),
        (10,  0.07, 0.18, 0.33),
        (20,  0.09, 0.24, 0.44),
        (30,  0.10, 0.27, 0.50),
        (50,  0.12, 0.32, 0.60),
        (75,  0.15, 0.40, 0.74),
        (100, 0.19, 0.51, 0.93),
        (130, 0.24, 0.63, 1.14),
        (160, 0.30, 0.78, 1.38),
        (200, 0.38, 0.96, 1.68),
        (250, 0.46, 1.14, 1.98),
        (300, 0.54, 1.30, 2.24),
    ],
    "sand": [
        (5,   0.08, 0.22, 0.42),
        (10,  0.10, 0.27, 0.50),
        (20,  0.12, 0.32, 0.60),
        (30,  0.14, 0.37, 0.68),
        (50,  0.17, 0.44, 0.80),
        (75,  0.20, 0.52, 0.94),
        (100, 0.24, 0.62, 1.10),
        (150, 0.30, 0.76, 1.34),
        (200, 0.36, 0.90, 1.57),
    ],
    "recovery": [
        (5,   0.10, 0.26, 0.48),
        (20,  0.12, 0.31, 0.58),
        (50,  0.14, 0.37, 0.68),
        (100, 0.18, 0.47, 0.85),
        (150, 0.22, 0.57, 1.02),
        (200, 0.26, 0.67, 1.18),
        (300, 0.32, 0.80, 1.40),
    ],
    # Green: distance in FEET
    "green": [
        (1,   0.00, 0.01, 0.02),  # everyone holes a 1-footer
        (2,   0.01, 0.03, 0.06),
        (3,   0.02, 0.07, 0.14),
        (4,   0.03, 0.10, 0.20),
        (5,   0.04, 0.13, 0.26),
        (6,   0.05, 0.16, 0.32),
        (8,   0.07, 0.21, 0.40),
        (10,  0.08, 0.26, 0.48),
        (12,  0.10, 0.30, 0.55),
        (15,  0.11, 0.34, 0.62),
        (20,  0.13, 0.40, 0.72),  # anchor: hcp10≈+0.40
        (25,  0.14, 0.44, 0.79),
        (30,  0.16, 0.48, 0.86),
        (40,  0.18, 0.53, 0.95),
        (50,  0.19, 0.57, 1.02),
        (75,  0.22, 0.64, 1.14),
        (100, 0.25, 0.72, 1.28),
    ],
}

# ── Build all four profiles ───────────────────────────────────────────────────

def _apply_deltas(raw_table, delta_table, delta_idx):
    """Add delta[delta_idx] to each Tour value, interpolating delta by distance."""
    d_xs, d_ys = _build([(row[0], row[1 + delta_idx]) for row in delta_table])
    result = []
    for dist, tour_val in raw_table:
        delta = _interp(d_xs, d_ys, dist)
        result.append((dist, round(tour_val + delta, 4)))
    return result


def _build_profile(delta_idx):
    """Build a full profile dict. delta_idx: 0=scratch, 1=hcp10, 2=bogey."""
    tables = {}
    for lie in ("tee", "fairway", "rough", "sand", "recovery", "green"):
        tables[lie] = _build(_apply_deltas(_TOUR_RAW[lie], _DELTAS[lie], delta_idx))
    tables["fringe"]  = tables["rough"]
    tables["unknown"] = tables["rough"]
    tables["hole"]    = _build([(0, 0.0)])
    return tables


_tour_profile = {}
for lie, raw in _TOUR_RAW.items():
    _tour_profile[lie] = _build(raw)
_tour_profile["fringe"]  = _tour_profile["rough"]
_tour_profile["unknown"] = _tour_profile["rough"]
_tour_profile["hole"]    = _build([(0, 0.0)])

PROFILES = {
    "tour":    _tour_profile,
    "scratch": _build_profile(0),
    "10":      _build_profile(1),
    "bogey":   _build_profile(2),
}

AVAILABLE_PROFILES = list(PROFILES.keys())

# Friendly display names
PROFILE_LABELS = {
    "tour":    "PGA Tour (Broadie / ShotLink)",
    "scratch": "Scratch (0 handicap)",
    "10":      "10 Handicap",
    "bogey":   "Bogey Golfer (18 handicap)",
}

# ── Public API ────────────────────────────────────────────────────────────────

def get_profile(name: str) -> dict:
    """Return benchmark table dict for the named profile."""
    key = str(name).lower().strip()
    if key == "0": key = "scratch"
    if key == "18": key = "bogey"
    if key not in PROFILES:
        raise ValueError(
            f"Unknown benchmark profile {name!r}. "
            f"Available: {AVAILABLE_PROFILES}"
        )
    return PROFILES[key]


def expected_strokes(lie: str, dist_yards: float, profile: str = "tour") -> float | None:
    """
    Expected strokes to hole from (lie, dist_yards) for the given profile.
    For putting (lie='green') dist_yards is converted to feet internally.
    Returns None for invalid inputs.
    """
    if lie == "hole" or dist_yards == 0:
        return 0.0
    if dist_yards is None or (isinstance(dist_yards, float) and math.isnan(dist_yards)):
        return None

    tables  = get_profile(profile)
    lie_key = lie.strip().lower()
    xs, ys  = tables.get(lie_key) or tables["unknown"]

    dist = dist_yards * 3.0 if lie_key == "green" else dist_yards
    return _interp(xs, ys, dist)
