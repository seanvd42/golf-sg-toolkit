# ⛳ Golf Strokes Gained Toolkit

Automatically pull your Garmin Connect golf data and calculate strokes gained
(SG) for every shot — across four benchmark profiles — then push results to
Google Sheets.

---

## Quick Start

```bash
pip install garminconnect garth requests
python run.py
```

The interactive menu handles everything:
```
  What would you like to do?
    [1]  Fetch latest round from Garmin + run full pipeline
    [2]  Fetch last N rounds from Garmin + run full pipeline
    [3]  Fetch ALL rounds from Garmin + run full pipeline
    [4]  Re-run pipeline on already-downloaded data  (skip fetch)
    [5]  Run demo with synthetic data  (no Garmin account needed)

  Benchmark — compare yourself against:
    [1]  Tour Pro   (PGA Tour — Broadie / ShotLink data)
    [2]  Scratch    (0 handicap)
    [3]  10 Handicap
    [4]  Bogey      (18 handicap — typical club golfer)
```

SG calculations are run for **all four profiles** automatically and stored
together, so you can compare across benchmarks without re-running.

---

## Output Files

| File | Contents |
|------|----------|
| `data/shots.csv` | Every shot: hole, club, start/end lie & distance |
| `data/sg_shots.csv` | Same + benchmark values + SG per shot (last profile run) |
| `data/sg_summary.csv` | One row per round × profile: SG totals, avg, median, shot counts |
| `data/scorecard.csv` | Per-hole: strokes, FW, GIR, bGIR, approaches, chips, putts, SG |

---

## Google Sheets

### Setup

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

1. Create a Google Cloud project, enable the **Google Sheets API**
2. Create **OAuth 2.0 credentials** (Desktop app), download as `credentials.json`
3. Set `GOOGLE_SHEET_ID` in `config.py` or as env var

### Tabs written

| Tab | Contents | Update mode |
|-----|----------|-------------|
| **Hole by Hole** | Per-hole scorecard rows | Append (no duplicates) |
| **Shot Detail** | Every shot with SG values | Append (no duplicates) |
| **Strokes Gained** | One block per round × benchmark — all detail | Overwrite each run |
| **Breakdown** | Formula-driven summary with live filter cells | Overwrite each run |

### Strokes Gained tab

One block per round × benchmark profile (4 blocks per round), sorted oldest
to newest. Each block shows Drives / Long Approach / Short Approach / Putting
rows with Total Shots, Total SG, Avg/Shot, Median/Shot, and Est. Impact.
Category rows have red→white→green conditional formatting; the Total row does not.

### Breakdown tab

A compact summary table with two filter cells you edit directly in the sheet:

```
A1: Last X Rounds    A2: 5        ← edit this number (0 = all rounds)
A4: Benchmark        A5: Scratch  ← edit this label (Tour / Scratch / 10 Handicap / Bogey)

     Category      Total Shots  Total SG  Avg/Shot  Median/Shot  Est. Impact
     Drives              72       -13.12     -0.18        -0.24       -17.28
     Long Approach       64       -19.81     -0.31        -0.35       -22.40
     Short Approach      97       -34.42     -0.35        -0.39       -37.83
     Putting            151       -19.53     -0.13        -0.79      -119.29
     Total              384       -86.87     -0.98        -1.77           —
```

All data columns recalculate instantly when you change A2 or A5.
Category rows have conditional formatting (red→white→green).
The Total row is bold with no conditional formatting.

**Estimated Impact** = weighted median SG/shot × total shots in category
(total shots includes zero-SG shots excluded from avg/median calculations).

---

## Configuration (`config.py`)

```python
SHORT_APPROACH_THRESHOLD_YARDS = 75   # chips vs approaches distance cutoff

EXCLUDE_ZERO_SG = True     # exclude shots where SG == 0.0 (GPS artifacts)

BREAKDOWN_LAST_N_ROUNDS = 0   # 0 = all rounds (Breakdown tab filter default)
BREAKDOWN_FROM_DATE = ""      # "" = no date filter

GOOGLE_SHEET_ID = "..."
```

---

## How Strokes Gained Works

```
SG = benchmark(start_lie, start_distance) − 1 − benchmark(end_lie, end_distance)
```

Positive = better than benchmark; negative = worse.

### Benchmark profiles

| Profile | Source |
|---------|--------|
| **Tour** | PGA Tour ShotLink (Broadie, *Every Shot Counts*, 2004-2012) |
| **Scratch** | Calibrated from Arccos/Shot Scope published data points |
| **10 Handicap** | Calibrated anchor: 160 yd fairway → +0.85 vs Tour |
| **Bogey (18)** | Calibrated from putts/round and scoring differential data |

Amateur tables are reasoned estimates consistent with published data, not
from a proprietary database. No free equivalent to Broadie's tables exists.

### SG categories

- **Drives** — tee shots on par-4/5
- **Long approaches** — shots starting beyond `SHORT_APPROACH_THRESHOLD_YARDS`
- **Short approaches** — shots within threshold, not on green (chips)
- **Putting** — shots from the green

---

## Files

| File | Purpose |
|------|---------|
| `run.py` | **Start here** — interactive one-click launcher |
| `garmin_fetch.py` | Fetches data from Garmin Connect (Python) |
| `garmin_export.js` | Alternative: browser bookmarklet for Garmin export |
| `parse_shots.py` | Parses Garmin JSON → shots CSV |
| `benchmarks.py` | SG benchmark tables for all four profiles |
| `strokes_gained.py` | Computes SG per shot, aggregates by round + profile |
| `format_scorecard.py` | Formats per-hole scorecard rows |
| `upload_to_sheets.py` | Pushes CSVs to Google Sheets |
| `config.py` | All settings in one place |

---

## Hardware

Tested with **Garmin S70** watch + **CT10** club sensors. CT10s provide
automatic club detection and shot tracking. Without CT10s, shot distances
and lie types are still recorded via GPS but club names will show as
numeric IDs.

---

## Troubleshooting

**"Authentication failed"** — If you use Google/Apple sign-in for Garmin
Connect, set a Garmin-specific password first (Garmin Connect → Account →
Sign-in & Security).

**Club names show as numbers** — The CT10 club mapping requires a successful
`/api/v2/club/{id}` call per club. Check your Garmin Connect app has fully
synced and club sets are configured.

**Shot data missing** — Ensure rounds have fully synced in the Garmin
Connect mobile app before running the fetch.

**Google Sheets upload fails** — Delete `token.json` and re-run to force
re-authorisation.

**Zero SG values** — Set `EXCLUDE_ZERO_SG = False` in `config.py` to
include them. Zero SG usually means identical start/end GPS coordinates
(a GPS artifact), not a perfectly average shot.
