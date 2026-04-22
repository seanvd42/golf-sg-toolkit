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
| **Breakdown** | SG summary aggregated across rounds, all profiles | Overwrite each run |

### Breakdown tab

The Breakdown tab shows one section per benchmark profile:

```
PGA Tour (Broadie / ShotLink)   3 rounds  2026-01-15 → 2026-04-18
Category        Rounds  Total Shots  Total SG  Avg/Shot  Median/Shot  Est. Impact
Total                3           97    -29.55    -0.305       -0.454      -44.038
Drives               3           18     -7.75    -0.430       -0.397       -7.146
Long Approach        3           18     -6.46    -0.359       -0.433       -7.794
Short Approach       3           22     -7.92    -0.360       -0.366       -8.074
Putting              3           39     -7.43    -0.191       -0.840      -32.760
```

**Estimated Impact** = median SG per shot × total shots in that category
(including shots excluded from SG calculation due to zero values).
This gives a more realistic picture of category impact than the raw total.

**Conditional formatting**: Total SG, Avg/Shot, Median/Shot, and Est. Impact
columns are colour-graded red (negative) → white (0) → green (positive).

### Filtering the Breakdown tab

Edit in `config.py`:
```python
BREAKDOWN_LAST_N_ROUNDS = 5    # show only last 5 rounds (0 = all)
BREAKDOWN_FROM_DATE = "2026-01-01"  # show rounds on/after this date
```

---

## Configuration (`config.py`)

```python
SHORT_APPROACH_THRESHOLD_YARDS = 75   # chips vs approaches distance cutoff

EXCLUDE_ZERO_SG = True     # exclude shots where SG == 0.0 (GPS artifacts)

BENCHMARK_PROFILE = "tour" # default profile for single-profile runs
                           # options: "tour" | "scratch" | "10" | "bogey"

BREAKDOWN_LAST_N_ROUNDS = 0   # 0 = all rounds
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
