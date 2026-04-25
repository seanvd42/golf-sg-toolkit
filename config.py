"""
config.py — Central configuration for the Golf SG Toolkit.
Edit these values to match your setup.
"""

# ── Garmin credentials ────────────────────────────────────────────────────────
# Set via environment variables (preferred) or hardcode here (not recommended).
import os

GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL", "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "yourpassword")

# ── Strokes Gained thresholds ─────────────────────────────────────────────────
# Shots STARTING from farther than this distance are "long approaches / drives".
# Shots STARTING from within this distance (but not on the green) are "short
# approaches / chips / around the green".
SHORT_APPROACH_THRESHOLD_YARDS = 100  # ← tune this to your liking

# Exclude shots where SG calculates to exactly 0.0.
# Zero-SG almost always means bad/missing GPS data (start == end distance),
# not a genuinely average shot. Set to False to include them.
EXCLUDE_ZERO_SG = True

# ── Breakdown tab filters ─────────────────────────────────────────────────────
# BREAKDOWN_LAST_N_ROUNDS: show only the last N rounds per profile. 0 = all.
BREAKDOWN_LAST_N_ROUNDS = 0

# BREAKDOWN_FROM_DATE: show only rounds on or after this date. "" = all.
# Format: "YYYY-MM-DD"  e.g. "2026-01-01"
BREAKDOWN_FROM_DATE = ""

# ── Scorecard column mapping ──────────────────────────────────────────────────
# These match the columns in YOUR existing tracking sheet (Step 5).
# Change the sheet tab names if yours differ.
SHEET_ROUND_TAB      = "Rounds"       # tab where each round summary lives
SHEET_HOLE_TAB       = "Hole by Hole" # tab where per-hole rows live
SHEET_SG_TAB         = "Strokes Gained" # tab for SG output (will be created if absent)

# ── Google Sheets ─────────────────────────────────────────────────────────────
GOOGLE_SHEET_ID       = os.environ.get("GOOGLE_SHEET_ID", "YOUR_SHEET_ID_HERE")
GOOGLE_CREDENTIALS_FILE = "credentials.json"  # OAuth2 service-account JSON from Google Cloud

# ── Lie type normalisation ────────────────────────────────────────────────────
# Garmin uses various internal strings for lie types.  Map them to the canonical
# values used by the SG benchmark table.
LIE_ALIAS: dict[str, str] = {
    # Garmin → canonical
    "tee":          "tee",
    "teebox":       "tee",
    "fairway":      "fairway",
    "light rough":  "rough",
    "rough":        "rough",
    "heavy rough":  "rough",
    "bunker":       "sand",
    "sand":         "sand",
    "greenside bunker": "sand",
    "recovery":     "recovery",
    "trees":        "recovery",
    "penalty":      "rough",       # conservative—treat as rough
    "green":        "green",
    "fringe":       "rough",       # fringe treated as rough for benchmarking
    "hole":         "hole",        # ball holed
}

# ── Output file paths ─────────────────────────────────────────────────────────
DATA_DIR               = "data"
SHOTS_CSV              = f"{DATA_DIR}/shots.csv"
SG_SHOTS_CSV           = f"{DATA_DIR}/sg_shots.csv"
SG_SUMMARY_CSV         = f"{DATA_DIR}/sg_summary.csv"
SCORECARD_CSV          = f"{DATA_DIR}/scorecard.csv"
