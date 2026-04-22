"""
upload_to_sheets.py — Step 5
══════════════════════════════
Pushes generated CSVs into your existing Google Sheet.

Tabs written
────────────
    "Hole by Hole"   ← scorecard.csv  (keyed by round_id + hole_number)
    "Shot Detail"    ← sg_shots.csv   (keyed by round_id + hole + shot)
    "Breakdown"      ← sg_summary.csv (aggregated across rounds, all profiles)
                       Replaces the old "Strokes Gained" tab.

Duplicate logic
───────────────
Rows are keyed by (round_id, benchmark_profile, hole/shot where applicable).
Re-running with a different benchmark profile writes NEW rows rather than
skipping — so all four profiles accumulate over time.

Breakdown tab
─────────────
Overwrites completely each run. Configurable via:
    BREAKDOWN_LAST_N_ROUNDS  — show only last N rounds (0 = all)
    BREAKDOWN_FROM_DATE      — show rounds on/after YYYY-MM-DD ("" = all)
Shows one section per benchmark profile, each with 5 category rows:
    Category | Rounds | Total Shots | Total SG | Avg/Shot | Median/Shot | Est. Impact
Conditional formatting: red (negative) → white (0) → green (positive).

Prerequisites
─────────────
    pip install google-auth google-auth-oauthlib google-api-python-client
    Set GOOGLE_SHEET_ID in config.py or as env var GOOGLE_SHEET_ID.
    Place credentials.json (OAuth2 desktop app) in this folder.
"""

import csv, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE,
    SCORECARD_CSV, SG_SUMMARY_CSV, SG_SHOTS_CSV,
    SHEET_HOLE_TAB,
)

# ── Breakdown filter settings — edit here or override in config.py ────────────
try:
    from config import BREAKDOWN_LAST_N_ROUNDS
except ImportError:
    BREAKDOWN_LAST_N_ROUNDS = 0    # 0 = all rounds

try:
    from config import BREAKDOWN_FROM_DATE
except ImportError:
    BREAKDOWN_FROM_DATE = ""       # "" = no date filter, else "YYYY-MM-DD"

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False
    print("⚠️  google-api-python-client not installed.")
    print("   Run: pip install google-auth google-auth-oauthlib google-api-python-client")

SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_FILE     = "token.json"
HOLE_TAB       = SHEET_HOLE_TAB
SHOT_TAB       = "Shot Detail"
BREAKDOWN_TAB  = "Breakdown"


# ── auth ──────────────────────────────────────────────────────────────────────

def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)


# ── sheet helpers ─────────────────────────────────────────────────────────────

def get_or_create_tab(service, sid, name):
    meta     = service.spreadsheets().get(spreadsheetId=sid).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if name not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"addSheet": {"properties": {"title": name}}}]},
        ).execute()
        print(f"  Created tab: {name}")
    # Return the numeric sheetId needed for formatting
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == name:
            return s["properties"]["sheetId"]
    return 0


def read_tab(service, sid, name):
    result = service.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{name}'"
    ).execute()
    return result.get("values", [])


def write_rows(service, sid, name, rows):
    """Append rows to tab."""
    service.spreadsheets().values().append(
        spreadsheetId=sid,
        range=f"'{name}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def overwrite_tab(service, sid, name, rows):
    """Clear tab and write rows from A1."""
    service.spreadsheets().values().clear(
        spreadsheetId=sid, range=f"'{name}'"
    ).execute()
    if rows:
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"'{name}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()


def ensure_header(service, sid, name, header):
    if not read_tab(service, sid, name):
        write_rows(service, sid, name, [header])


# ── conditional formatting ────────────────────────────────────────────────────

def _color(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

def add_gradient_format(service, sid, sheet_id, start_row, end_row, col_indices):
    """
    Apply red→white→green gradient conditional formatting to specified columns.
    start_row / end_row are 0-indexed, inclusive.
    col_indices: list of 0-indexed column numbers.
    """
    requests = []
    for col in col_indices:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId":          sheet_id,
                        "startRowIndex":    start_row,
                        "endRowIndex":      end_row + 1,
                        "startColumnIndex": col,
                        "endColumnIndex":   col + 1,
                    }],
                    "gradientRule": {
                        "minpoint": {
                            "colorStyle": {"rgbColor": _color(220, 80,  80)},
                            "type": "MIN",
                        },
                        "midpoint": {
                            "colorStyle": {"rgbColor": _color(255, 255, 255)},
                            "type": "NUMBER",
                            "value": "0",
                        },
                        "maxpoint": {
                            "colorStyle": {"rgbColor": _color(80,  180, 80)},
                            "type": "MAX",
                        },
                    },
                },
                "index": 0,
            }
        })

    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": requests}
        ).execute()


def clear_conditional_formats(service, sid, sheet_id):
    """Remove all existing conditional format rules from a sheet."""
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"deleteConditionalFormatRule": {
                "sheetId": sheet_id, "index": 0
            }}]},
        ).execute()
    except Exception:
        pass  # No rules to delete — fine


# ── upload functions ──────────────────────────────────────────────────────────

def upload_scorecard(service, sid):
    if not os.path.exists(SCORECARD_CSV):
        print(f"  Skipping {HOLE_TAB} (no scorecard.csv)")
        return
    get_or_create_tab(service, sid, HOLE_TAB)

    with open(SCORECARD_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows   = list(reader)
        header = reader.fieldnames or []

    ensure_header(service, sid, HOLE_TAB, header)

    existing = read_tab(service, sid, HOLE_TAB)
    ex_keys  = set()
    if len(existing) > 1:
        h = existing[0]
        try: rc, hc = h.index("round_id"), h.index("hole_number")
        except ValueError: rc, hc = 0, 3
        ex_keys = {(r[rc], r[hc]) for r in existing[1:] if len(r) > max(rc,hc)}

    new = [[row.get(c,"") for c in header] for row in rows
           if (row.get("round_id",""), row.get("hole_number","")) not in ex_keys]

    if new:
        write_rows(service, sid, HOLE_TAB, new)
        print(f"  '{HOLE_TAB}': appended {len(new)} hole row(s)")
    else:
        print(f"  '{HOLE_TAB}': no new rows")


def upload_shot_detail(service, sid):
    if not os.path.exists(SG_SHOTS_CSV):
        print(f"  Skipping {SHOT_TAB} (no sg_shots.csv)")
        return
    get_or_create_tab(service, sid, SHOT_TAB)

    with open(SG_SHOTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows   = list(reader)
        header = reader.fieldnames or []

    ensure_header(service, sid, SHOT_TAB, header)

    existing = read_tab(service, sid, SHOT_TAB)
    ex_keys  = set()
    if len(existing) > 1:
        h = existing[0]
        try: rc, hc, sc = h.index("round_id"), h.index("hole_number"), h.index("shot_number")
        except ValueError: rc, hc, sc = 0, 3, 7
        ex_keys = {(r[rc], r[hc], r[sc]) for r in existing[1:]
                   if len(r) > max(rc, hc, sc)}

    new = [[row.get(c,"") for c in header] for row in rows
           if (row.get("round_id",""), row.get("hole_number",""),
               row.get("shot_number","")) not in ex_keys]

    if new:
        write_rows(service, sid, SHOT_TAB, new)
        print(f"  '{SHOT_TAB}': appended {len(new)} shot row(s)")
    else:
        print(f"  '{SHOT_TAB}': no new shots")


def upload_breakdown(service, sid):
    """
    Build the Breakdown tab: one section per benchmark profile, summarising
    performance across all rounds (filtered by BREAKDOWN_LAST_N_ROUNDS /
    BREAKDOWN_FROM_DATE).

    Columns: Category | Rounds | Total Shots | Total SG | Avg/Shot | Median/Shot | Est. Impact
    Conditional formatting on Total SG, Avg/Shot, Median/Shot, Est. Impact.
    """
    if not os.path.exists(SG_SUMMARY_CSV):
        print(f"  Skipping {BREAKDOWN_TAB} (no sg_summary.csv)")
        return

    sheet_id = get_or_create_tab(service, sid, BREAKDOWN_TAB)

    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        all_rounds = list(csv.DictReader(f))

    # ── filter rounds ─────────────────────────────────────────────────────────
    def _filter(rounds):
        if BREAKDOWN_FROM_DATE:
            rounds = [r for r in rounds if r.get("round_date","") >= BREAKDOWN_FROM_DATE]
        # Deduplicate: keep one entry per (round_id, profile) — latest wins
        seen, deduped = set(), []
        for r in reversed(rounds):
            k = (r["round_id"], r["benchmark_profile"])
            if k not in seen:
                seen.add(k)
                deduped.append(r)
        deduped.reverse()
        if BREAKDOWN_LAST_N_ROUNDS > 0:
            # Per profile: keep last N unique round_ids
            from collections import defaultdict
            by_profile = defaultdict(list)
            for r in deduped:
                by_profile[r["benchmark_profile"]].append(r)
            filtered = []
            for p, rs in by_profile.items():
                unique_rids = []
                seen_rids   = set()
                for r in reversed(rs):
                    if r["round_id"] not in seen_rids:
                        seen_rids.add(r["round_id"])
                        unique_rids.append(r["round_id"])
                    if len(unique_rids) == BREAKDOWN_LAST_N_ROUNDS:
                        break
                keep = {r["round_id"] for r in rs if r["round_id"] in seen_rids}
                filtered.extend(r for r in rs if r["round_id"] in keep)
            return filtered
        return deduped

    rounds = _filter(all_rounds)

    # ── build output rows ─────────────────────────────────────────────────────
    from benchmarks import PROFILE_LABELS, AVAILABLE_PROFILES
    import statistics

    CATS = [
        ("Total",          "sg_total"),
        ("Drives",         "sg_drives"),
        ("Long Approach",  "sg_long_approach"),
        ("Short Approach", "sg_short_approach"),
        ("Putting",        "sg_putting"),
    ]

    def _ff(v):
        try:    return float(v)
        except: return None

    def _fmt(v, sign=True):
        if v is None or v == "": return ""
        try:    return round(float(v), 3)
        except: return v

    output_rows     = []
    format_ranges   = []   # (start_row, end_row) for gradient formatting
    header_rows_idx = []   # row indices of section headers (for bold)

    for profile in AVAILABLE_PROFILES:
        profile_rounds = [r for r in rounds if r["benchmark_profile"] == profile]
        if not profile_rounds:
            continue

        n_rounds    = len({r["round_id"] for r in profile_rounds})
        date_range  = ""
        if profile_rounds:
            dates = sorted(r["round_date"] for r in profile_rounds)
            date_range = f"{dates[0]} → {dates[-1]}" if len(dates) > 1 else dates[0]

        # Section header
        header_rows_idx.append(len(output_rows))
        output_rows.append([
            f"{PROFILE_LABELS[profile]}",
            f"{n_rounds} round(s)  {date_range}",
            "", "", "", "", ""
        ])

        col_header = ["Category", "Rounds", "Total Shots", "Total SG",
                      "Avg / Shot", "Median / Shot", "Est. Impact"]
        output_rows.append(col_header)

        data_start = len(output_rows)

        for label, key in CATS:
            # Aggregate across rounds for this profile + category
            all_vals_sg    = []
            all_vals_med   = []
            total_shots_all = 0

            for r in profile_rounds:
                # SG values: reconstitute from mean × shots (approx) — or use total directly
                total_sg_r = _ff(r.get(key, ""))
                shots_r    = _ff(r.get(f"{key}_shots", 0)) or 0
                mean_r     = _ff(r.get(f"{key}_mean_per_shot", ""))
                median_r   = _ff(r.get(f"{key}_median_per_shot", ""))
                shots_all_r = _ff(r.get(f"{key}_shots_all", shots_r)) or shots_r

                if total_sg_r is not None and shots_r > 0:
                    # Rebuild individual SG values as mean repeated shots times
                    # (best we can do from summary data; exact values in sg_shots.csv)
                    all_vals_sg.append(total_sg_r)
                if median_r is not None:
                    all_vals_med.append((median_r, int(shots_r)))
                total_shots_all += int(shots_all_r)

            total_sg   = round(sum(all_vals_sg), 3) if all_vals_sg else ""
            avg_shot   = round(sum(all_vals_sg) / sum(
                              int(_ff(r.get(f"{key}_shots",0)) or 0)
                              for r in profile_rounds
                          ), 3) if all_vals_sg and total_shots_all > 0 else ""

            # Weighted median: weight each round's median by its shot count
            if all_vals_med:
                weighted = sorted(all_vals_med, key=lambda x: x[0])
                total_w  = sum(w for _, w in weighted)
                cumul    = 0
                med_agg  = weighted[0][0]
                for val, w in weighted:
                    cumul += w
                    if cumul >= total_w / 2:
                        med_agg = val
                        break
                med_agg = round(med_agg, 3)
            else:
                med_agg = ""

            # Estimated impact = weighted median × total shots (including zeros)
            est_impact = round(med_agg * total_shots_all, 3) \
                         if isinstance(med_agg, float) and total_shots_all > 0 else ""

            output_rows.append([
                label,
                n_rounds,
                total_shots_all,
                _fmt(total_sg),
                _fmt(avg_shot),
                _fmt(med_agg),
                _fmt(est_impact),
            ])

        format_ranges.append((data_start, len(output_rows) - 1))
        output_rows.append([""] * 7)   # spacer

    # ── write to sheet ────────────────────────────────────────────────────────
    overwrite_tab(service, sid, BREAKDOWN_TAB, output_rows)

    # ── conditional formatting ────────────────────────────────────────────────
    # Clear existing rules first
    for _ in range(10):
        clear_conditional_formats(service, sid, sheet_id)

    # Columns 3,4,5,6 = Total SG, Avg/Shot, Median/Shot, Est. Impact (0-indexed)
    fmt_cols = [3, 4, 5, 6]
    for start_row, end_row in format_ranges:
        if start_row <= end_row:
            add_gradient_format(service, sid, sheet_id, start_row, end_row, fmt_cols)

    print(f"  '{BREAKDOWN_TAB}': wrote {len(output_rows)} rows across "
          f"{len(format_ranges)} profile(s)")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if not GSHEETS_AVAILABLE:
        sys.exit(1)

    if not GOOGLE_SHEET_ID or GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
        print("❌  Set GOOGLE_SHEET_ID in config.py (or as env var) before uploading.")
        sys.exit(1)

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌  Missing {GOOGLE_CREDENTIALS_FILE}.")
        print("   Download OAuth2 credentials from Google Cloud Console.")
        sys.exit(1)

    print("Authenticating with Google Sheets…")
    service = get_service()
    print(f"Uploading to spreadsheet: {GOOGLE_SHEET_ID}")

    upload_scorecard(service, GOOGLE_SHEET_ID)
    upload_shot_detail(service, GOOGLE_SHEET_ID)
    upload_breakdown(service, GOOGLE_SHEET_ID)

    print("✅  Upload complete.")


if __name__ == "__main__":
    main()
