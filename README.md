# ⛳ Golf Strokes Gained Toolkit

Automatically pull your Garmin Connect golf data and calculate strokes gained
(drives, long approaches, short approaches, putting) for every shot in every round.

---

## Quick Start

```bash
# 1. Install dependencies
pip install garminconnect garth requests

# 2. Run — that's it
python run.py
```

You'll see a menu like this:

```
  What would you like to do?

    [1]  Fetch latest round from Garmin + run full pipeline
    [2]  Fetch last N rounds from Garmin + run full pipeline
    [3]  Fetch ALL rounds from Garmin + run full pipeline
    [4]  Re-run pipeline on already-downloaded data  (skip fetch)
    [5]  Run demo with synthetic data  (no Garmin account needed)
```

Pick **[1]** for your most recent round. It will prompt for your Garmin email and
password (once), cache a login token, and run everything automatically.

---

## Output Files

| File | Contents |
|------|----------|
| `data/shots.csv` | Every shot: hole, club, start/end lie, distance |
| `data/sg_shots.csv` | Same + benchmark values + strokes gained per shot |
| `data/sg_summary.csv` | Round totals: SG drives / long app / short app / putting |
| `data/scorecard.csv` | Per-hole: strokes, FW hit, GIR, bGIR, approaches, chips, putts, SG |

---

## Optional: Google Sheets Auto-Upload

To have results pushed automatically to your tracking sheet:

1. Install the extra packages:
   ```bash
   pip install google-auth google-auth-oauthlib google-api-python-client
   ```

2. Create a Google Cloud project:
   - Go to https://console.cloud.google.com
   - Enable the **Google Sheets API**
   - Create **OAuth 2.0 credentials** (Desktop app type)
   - Download as `credentials.json` and place it in this folder

3. Edit `config.py`:
   ```python
   GOOGLE_SHEET_ID = "your-sheet-id-here"   # from the URL of your sheet
   ```

4. Run `python run.py` — on first use it opens a browser to authorise;
   subsequent runs are fully automatic.

The script writes to three tabs in your sheet (creating them if needed):
- **Hole by Hole** — per-hole scorecard rows (matches your existing layout)
- **Strokes Gained** — round-level SG summary
- **Shot Detail** — every individual shot with SG values

Duplicate rounds are detected and skipped automatically.

---

## Configuration

All settings live in `config.py`. The ones you're most likely to change:

```python
SHORT_APPROACH_THRESHOLD_YARDS = 75   # shots inside this = chips; outside = approaches

GOOGLE_SHEET_ID = "YOUR_SHEET_ID_HERE"

# Credentials — better to use environment variables:
# export EMAIL=you@email.com
# export PASSWORD=yourpassword
```

---

## How Strokes Gained Works

Each shot's SG is calculated as:

```
SG = benchmark(start_lie, start_distance) - 1 - benchmark(end_lie, end_distance)
```

Where `benchmark` is the PGA Tour average strokes-to-hole from that position,
taken from Mark Broadie's Every Shot Counts (2014) tables. Positive SG means
you did better than PGA Tour average; negative means worse.

**Categories:**
- **Drives** - tee shots on par-4/5 starting beyond threshold distance
- **Long approaches** - non-tee shots starting beyond threshold distance
- **Short approaches** - shots starting within threshold, not on green (chips)
- **Putting** - shots starting on the green

---

## Files at a Glance

| File | Purpose |
|------|---------|
| `run.py` | **Start here** - interactive one-click launcher |
| `garmin_fetch.py` | Fetches data from Garmin Connect (Python, no browser needed) |
| `garmin_export.js` | Alternative: browser bookmarklet (paste into DevTools console) |
| `parse_shots.py` | Parses Garmin JSON -> shots CSV |
| `strokes_gained.py` | Computes SG per shot using Broadie benchmark tables |
| `format_scorecard.py` | Formats per-hole scorecard rows |
| `upload_to_sheets.py` | Pushes CSVs to Google Sheets |
| `config.py` | All settings in one place |

---

## Troubleshooting

**"Authentication failed"** - Double-check email/password. If you use Google/Apple
sign-in for Garmin Connect, you may need to set a Garmin-specific password first
(Garmin Connect -> Account -> Sign-in & Security).

**Shot data missing (distances/lies are blank)** - The CT10 auto-shot-detection
data is processed server-side by Garmin. Make sure your rounds have fully synced
in the Garmin Connect app before fetching.

**Lie types showing as "unknown"** - Garmin occasionally changes their internal
lie type strings. Add new mappings to LIE_ALIAS in config.py.

**Google Sheets upload fails** - Delete token.json and re-run to force re-authorisation.
