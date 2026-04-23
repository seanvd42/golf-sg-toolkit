"""
upload_to_sheets.py — Step 5
══════════════════════════════
Pushes generated CSVs into your Google Sheet.

Tabs written
────────────
  "Hole by Hole"    ← scorecard.csv  — appended, keyed by (round_id, hole_number)
  "Shot Detail"     ← sg_shots.csv   — appended, keyed by (round_id, hole, shot)
  "Strokes Gained"  ← one block of 5 category rows per round (all profiles stacked),
                       overwritten each run
  "Breakdown"       ← formula-driven summary table with two filter cells:
                         A2 = Last X Rounds  (integer, 0 = all)
                         A5 = Benchmark      (Tour / Scratch / 10 Handicap / Bogey)
                       Columns B-F calculate live from those filters.
                       Conditional formatting on category rows; NOT on Total row.
"""

import csv, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE,
    SCORECARD_CSV, SG_SUMMARY_CSV, SG_SHOTS_CSV,
    SHEET_HOLE_TAB,
)

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False
    print("⚠️  Run: pip install google-auth google-auth-oauthlib google-api-python-client")

SCOPES        = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_FILE    = "token.json"
HOLE_TAB      = SHEET_HOLE_TAB
SHOT_TAB      = "Shot Detail"
SG_TAB        = "Strokes Gained"
BREAKDOWN_TAB = "Breakdown"

from benchmarks import AVAILABLE_PROFILES, PROFILE_LABELS

# Map display name → profile key (used for Breakdown filter matching)
LABEL_TO_KEY = {v: k for k, v in PROFILE_LABELS.items()}
# Friendly display names shown in the filter cell
PROFILE_DISPLAY = {
    "tour":    "Tour",
    "scratch": "Scratch",
    "10":      "10 Handicap",
    "bogey":   "Bogey",
}
DISPLAY_TO_KEY = {v: k for k, v in PROFILE_DISPLAY.items()}


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

def get_sheet_id(service, sid, name):
    """Return numeric sheetId for a tab, creating it if needed."""
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == name:
            return s["properties"]["sheetId"]
    # Create tab
    service.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{"addSheet": {"properties": {"title": name}}}]},
    ).execute()
    print(f"  Created tab: {name}")
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == name:
            return s["properties"]["sheetId"]


def read_tab(service, sid, name):
    result = service.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{name}'"
    ).execute()
    return result.get("values", [])


def append_rows(service, sid, name, rows):
    service.spreadsheets().values().append(
        spreadsheetId=sid,
        range=f"'{name}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def overwrite_tab(service, sid, name, rows):
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
        append_rows(service, sid, name, [header])


# ── formatting helpers ────────────────────────────────────────────────────────

def _color(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}


def clear_conditional_formats(service, sid, sheet_id):
    """Remove ALL conditional format rules from a sheet (loop until gone)."""
    for _ in range(20):
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"deleteConditionalFormatRule": {
                    "sheetId": sheet_id, "index": 0
                }}]},
            ).execute()
        except Exception:
            break


def add_gradient(service, sid, sheet_id, start_row, end_row, col_indices):
    """
    Red → white (at 0) → green gradient on specified rows/cols (0-indexed, inclusive).
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
                        "minpoint": {"colorStyle": {"rgbColor": _color(220, 80,  80)},
                                     "type": "MIN"},
                        "midpoint": {"colorStyle": {"rgbColor": _color(255, 255, 255)},
                                     "type": "NUMBER", "value": "0"},
                        "maxpoint": {"colorStyle": {"rgbColor": _color(80,  180, 80)},
                                     "type": "MAX"},
                    },
                },
                "index": 0,
            }
        })
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": requests}
        ).execute()


def bold_cells(service, sid, sheet_id, row_indices, col_start=0, col_end=7):
    """Bold entire rows by 0-indexed row numbers."""
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId":          sheet_id,
                    "startRowIndex":    r,
                    "endRowIndex":      r + 1,
                    "startColumnIndex": col_start,
                    "endColumnIndex":   col_end,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        }
        for r in row_indices
    ]
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": requests}
        ).execute()


# ── upload: Hole by Hole ──────────────────────────────────────────────────────

def upload_scorecard(service, sid):
    if not os.path.exists(SCORECARD_CSV):
        print(f"  Skipping {HOLE_TAB} (no scorecard.csv)")
        return
    get_sheet_id(service, sid, HOLE_TAB)
    with open(SCORECARD_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows, header = list(reader), reader.fieldnames or []

    ensure_header(service, sid, HOLE_TAB, header)
    existing = read_tab(service, sid, HOLE_TAB)
    ex_keys  = set()
    if len(existing) > 1:
        h = existing[0]
        try: rc, hc = h.index("round_id"), h.index("hole_number")
        except ValueError: rc, hc = 0, 3
        ex_keys = {(r[rc], r[hc]) for r in existing[1:] if len(r) > max(rc, hc)}

    new = [[row.get(c,"") for c in header] for row in rows
           if (row.get("round_id",""), row.get("hole_number","")) not in ex_keys]
    if new:
        append_rows(service, sid, HOLE_TAB, new)
        print(f"  '{HOLE_TAB}': appended {len(new)} hole row(s)")
    else:
        print(f"  '{HOLE_TAB}': no new rows")


# ── upload: Shot Detail ───────────────────────────────────────────────────────

def upload_shot_detail(service, sid):
    if not os.path.exists(SG_SHOTS_CSV):
        print(f"  Skipping {SHOT_TAB} (no sg_shots.csv)")
        return
    get_sheet_id(service, sid, SHOT_TAB)
    with open(SG_SHOTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows, header = list(reader), reader.fieldnames or []

    ensure_header(service, sid, SHOT_TAB, header)
    existing = read_tab(service, sid, SHOT_TAB)
    ex_keys  = set()
    if len(existing) > 1:
        h = existing[0]
        try: rc,hc,sc = h.index("round_id"), h.index("hole_number"), h.index("shot_number")
        except ValueError: rc,hc,sc = 0,3,7
        ex_keys = {(r[rc],r[hc],r[sc]) for r in existing[1:]
                   if len(r) > max(rc,hc,sc)}

    new = [[row.get(c,"") for c in header] for row in rows
           if (row.get("round_id",""), row.get("hole_number",""),
               row.get("shot_number","")) not in ex_keys]
    if new:
        append_rows(service, sid, SHOT_TAB, new)
        print(f"  '{SHOT_TAB}': appended {len(new)} shot row(s)")
    else:
        print(f"  '{SHOT_TAB}': no new shots")


# ── upload: Strokes Gained (per-round blocks) ─────────────────────────────────

def upload_strokes_gained(service, sid):
    """
    One block per round per benchmark profile.
    Layout per block:
        Row 1: bold header — Date | Course | Benchmark
        Row 2: col headers — Category | Total Shots | Total SG | Avg/Shot | Median/Shot | Est. Impact
        Rows 3-6: drives / long_approach / short_approach / putting  (conditional formatting)
        Row 7: Total  (NO conditional formatting)
        Row 8: blank spacer
    Overwritten completely each run.
    """
    if not os.path.exists(SG_SUMMARY_CSV):
        print(f"  Skipping {SG_TAB} (no sg_summary.csv)")
        return

    sheet_id = get_sheet_id(service, sid, SG_TAB)

    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    # Sort: oldest round first, then by profile order
    profile_order = {p: i for i, p in enumerate(AVAILABLE_PROFILES)}
    all_rows.sort(key=lambda r: (r["round_date"], profile_order.get(r["benchmark_profile"], 99)))

    CATS = [
        ("Drives",         "sg_drives"),
        ("Long Approach",  "sg_long_approach"),
        ("Short Approach", "sg_short_approach"),
        ("Putting",        "sg_putting"),
    ]
    COL_HDR = ["Category", "Total Shots", "Total SG", "Avg / Shot", "Median / Shot", "Est. Impact"]

    def ff(v):
        try:    return round(float(v), 3)
        except: return ""

    output       = []   # list of rows (each row = list of cell values)
    bold_rows    = []   # 0-indexed row numbers to bold
    fmt_ranges   = []   # (start_row, end_row) 0-indexed for gradient formatting

    for r in all_rows:
        profile_key = r.get("benchmark_profile", "")
        profile_lbl = PROFILE_DISPLAY.get(profile_key, profile_key)

        # Block header row
        bold_rows.append(len(output))
        output.append([
            f"{r['round_date']}  —  {r['course_name']}  [{profile_lbl}]",
            "", "", "", "", ""
        ])

        # Column header row
        bold_rows.append(len(output))
        output.append(COL_HDR)

        cat_start = len(output)

        # Category rows
        for label, key in CATS:
            shots_all = ff(r.get(f"{key}_shots_all", r.get(f"{key}_shots", 0)))
            total_sg  = ff(r.get(key))
            avg       = ff(r.get(f"{key}_mean_per_shot"))
            median    = ff(r.get(f"{key}_median_per_shot"))
            est       = round(float(median) * int(float(shots_all)), 3) \
                        if isinstance(median, float) and shots_all != "" else ""
            output.append([label, shots_all, total_sg, avg, median, est])

        fmt_ranges.append((cat_start, len(output) - 1))

        # Total row (no conditional formatting)
        t_shots = ff(r.get("sg_total_shots_all", r.get("shots_counted", 0)))
        t_sg    = ff(r.get("sg_total"))
        t_avg   = ff(r.get("sg_total_mean_per_shot"))
        t_med   = ff(r.get("sg_total_median_per_shot"))
        t_est   = round(float(t_med) * int(float(t_shots)), 3) \
                  if isinstance(t_med, float) and t_shots != "" else ""
        bold_rows.append(len(output))
        output.append(["Total", t_shots, t_sg, t_avg, t_med, t_est])

        # Blank spacer
        output.append([""] * 6)

    # Write
    overwrite_tab(service, sid, SG_TAB, output)

    # Bold headers + Total rows
    bold_cells(service, sid, sheet_id, bold_rows, col_start=0, col_end=6)

    # Conditional formatting on category rows only (cols 2,3,4,5 = Total SG, Avg, Median, Est)
    clear_conditional_formats(service, sid, sheet_id)
    for start_row, end_row in fmt_ranges:
        add_gradient(service, sid, sheet_id, start_row, end_row, [2, 3, 4, 5])

    print(f"  '{SG_TAB}': wrote {len(all_rows)} round×profile block(s)")


# ── upload: Breakdown (formula-driven summary) ────────────────────────────────

def upload_breakdown(service, sid):
    """
    Formula-driven summary tab.

    Layout:
        A1: "Last X Rounds"    A2: 5          (user edits this number)
        A4: "Benchmark"        A5: "Scratch"  (user edits this label)

        B7:F7  — column headers
        B8:F11 — category rows (Drives / Long Approach / Short Approach / Putting)
        B12:F12 — Total row (no conditional formatting)

    Columns B-F use SUMIF/COUNTIF/IFERROR formulas referencing the raw data
    on the "Strokes Gained" tab so they recalculate instantly when A2 or A5 changes.

    Because Sheets formulas can't easily do "last N rounds median", we write
    the raw summary data to a hidden helper range and use SUMPRODUCT there.
    Simpler approach used here: write all summary data to a helper range on this
    tab (cols H onward, rows 2+) and SUMIF/AVERAGEIF against that.
    """
    if not os.path.exists(SG_SUMMARY_CSV):
        print(f"  Skipping {BREAKDOWN_TAB} (no sg_summary.csv)")
        return

    sheet_id = get_sheet_id(service, sid, BREAKDOWN_TAB)

    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        summary_rows = list(csv.DictReader(f))

    if not summary_rows:
        print(f"  '{BREAKDOWN_TAB}': no data")
        return

    # ── Helper data range ─────────────────────────────────────────────────────
    # Write raw data to columns H onwards (hidden from user view).
    # Columns: H=round_id, I=round_date, J=profile_display, K=rank(newest=1)
    #   then pairs: (shots_all, total_sg, avg, median) for each of 5 categories
    #
    # Helper header (row 2 = index 1 in 0-based)
    HELPER_CATS = [
        ("sg_drives",         "sg_drives_shots_all",         "sg_drives_mean_per_shot",         "sg_drives_median_per_shot"),
        ("sg_long_approach",  "sg_long_approach_shots_all",  "sg_long_approach_mean_per_shot",  "sg_long_approach_median_per_shot"),
        ("sg_short_approach", "sg_short_approach_shots_all", "sg_short_approach_mean_per_shot", "sg_short_approach_median_per_shot"),
        ("sg_putting",        "sg_putting_shots_all",        "sg_putting_mean_per_shot",        "sg_putting_median_per_shot"),
        ("sg_total",          "sg_total_shots_all",          "sg_total_mean_per_shot",          "sg_total_median_per_shot"),
    ]

    def ff(v):
        try:    return round(float(v), 6)
        except: return ""

    # Deduplicate: one row per (round_id, profile)
    seen, deduped = set(), []
    for r in summary_rows:
        k = (r["round_id"], r["benchmark_profile"])
        if k not in seen:
            seen.add(k)
            deduped.append(r)

    # Sort by date ascending; assign rank per profile (1 = most recent)
    deduped.sort(key=lambda r: r["round_date"])
    from collections import defaultdict
    profile_counts = defaultdict(int)
    # Count per profile for ranking
    profile_totals = defaultdict(int)
    for r in deduped:
        profile_totals[r["benchmark_profile"]] += 1

    # Assign recency rank (1 = newest) per profile
    profile_seen = defaultdict(int)
    for r in reversed(deduped):
        p = r["benchmark_profile"]
        profile_seen[p] += 1
        r["_rank"] = profile_seen[p]

    helper_header = ["round_id", "round_date", "profile", "rank",
                     "drv_shots","drv_sg","drv_avg","drv_med",
                     "long_shots","long_sg","long_avg","long_med",
                     "short_shots","short_sg","short_avg","short_med",
                     "putt_shots","putt_sg","putt_avg","putt_med",
                     "tot_shots","tot_sg","tot_avg","tot_med"]

    helper_data = [helper_header]
    for r in deduped:
        display = PROFILE_DISPLAY.get(r["benchmark_profile"], r["benchmark_profile"])
        row = [r["round_id"], r["round_date"], display, r["_rank"]]
        for sg_key, shots_key, avg_key, med_key in HELPER_CATS:
            shots_all = ff(r.get(shots_key, r.get(sg_key.replace("sg_","sg_") + "_shots", 0)))
            row.extend([
                shots_all,
                ff(r.get(sg_key)),
                ff(r.get(avg_key)),
                ff(r.get(med_key)),
            ])
        helper_data.append(row)

    # ── Formula cells ─────────────────────────────────────────────────────────
    # Helper data starts at H1 (col 8, 0-indexed col 7)
    # H = col 8  → H2:H{n+1} = round_id
    # I           → round_date
    # J           → profile display name  ← filter cell A5 must match this
    # K           → rank                  ← filter: rank <= A2 (or A2=0 → all)
    # L..O        → drives (shots, sg, avg, med)
    # P..S        → long_approach
    # T..W        → short_approach
    # X..AA       → putting
    # AB..AE      → total

    n = len(deduped)
    data_range = f"H2:AE{n+1}"  # helper data rows

    # Profile filter: J column (col 10, letter J)
    # Rank filter: K column (col 11, letter K), rank <= A2 when A2>0, else all
    # SUMPRODUCT used for conditional sum with two criteria

    def sumproduct_formula(val_col, shots_col=None):
        """
        Sum val_col where profile matches A5 AND rank <= A2 (or all if A2=0).
        If shots_col given, sum shots_col instead (for total shots).
        col is the letter of the data column.
        """
        j_col  = f"J2:J{n+1}"   # profile
        k_col  = f"K2:K{n+1}"   # rank
        v_col  = f"{val_col}2:{val_col}{n+1}"
        sc     = f"{shots_col}2:{shots_col}{n+1}" if shots_col else None

        profile_match  = f'({j_col}=A5)'
        rank_filter    = f'(($A$2=0)+($A$2>0)*({k_col}<=$A$2))'  # 0=all, else <=N
        data           = sc if sc else v_col

        return f'=IFERROR(SUMPRODUCT({profile_match}*{rank_filter}*({data})),"")'

    def avg_formula(val_col):
        """Weighted average = sum(sg) / sum(shots) for matched rows."""
        j_col  = f"J2:J{n+1}"
        k_col  = f"K2:K{n+1}"
        sg_col_r  = f"{val_col}2:{val_col}{n+1}"
        # avg = total_sg / shots — simpler to derive from sumproducts
        # We'll just use SUMPRODUCT(sg)/SUMPRODUCT(shots) — caller provides sg_col and shots_col
        return None  # handled inline below

    def med_formula(med_col, shots_col):
        """
        Weighted median approximation: SUMPRODUCT(med*shots)/SUMPRODUCT(shots).
        True median isn't available in Sheets without helper columns, so we use
        a shots-weighted average of per-round medians, which is a good approximation
        across many rounds.
        """
        j_col = f"J2:J{n+1}"
        k_col = f"K2:K{n+1}"
        m_col = f"{med_col}2:{med_col}{n+1}"
        s_col = f"{shots_col}2:{shots_col}{n+1}"
        match = f'({j_col}=A5)*(($A$2=0)+($A$2>0)*({k_col}<=$A$2))'
        return (f'=IFERROR('
                f'SUMPRODUCT({match}*IFERROR({m_col}*{s_col},0))'
                f'/SUMPRODUCT({match}*IFERROR({s_col},0)),"")')

    def est_formula(med_col, shots_col):
        """Est. Impact = weighted_median × total_shots_all."""
        j_col = f"J2:J{n+1}"
        k_col = f"K2:K{n+1}"
        m_col = f"{med_col}2:{med_col}{n+1}"
        s_col = f"{shots_col}2:{shots_col}{n+1}"
        match = f'({j_col}=A5)*(($A$2=0)+($A$2>0)*({k_col}<=$A$2))'
        wmed  = (f'IFERROR(SUMPRODUCT({match}*IFERROR({m_col}*{s_col},0))'
                 f'/SUMPRODUCT({match}*IFERROR({s_col},0)),0)')
        tot_s = f'SUMPRODUCT({match}*IFERROR({s_col},0))'
        return f'=IFERROR(ROUND(({wmed})*({tot_s}),3),"")'

    # Column letters for each category's (shots, sg, avg, med):
    # L=drives_shots, M=drives_sg, N=drives_avg, O=drives_med
    # P=long_shots,   Q=long_sg,   R=long_avg,   S=long_med
    # T=short_shots,  U=short_sg,  V=short_avg,  W=short_med
    # X=putt_shots,   Y=putt_sg,   Z=putt_avg,   AA=putt_med
    # AB=tot_shots,   AC=tot_sg,   AD=tot_avg,   AE=tot_med
    CAT_COLS = [
        ("Drives",         "L","M","N","O"),
        ("Long Approach",  "P","Q","R","S"),
        ("Short Approach", "T","U","V","W"),
        ("Putting",        "X","Y","Z","AA"),
    ]
    TOT_COLS = ("AB","AC","AD","AE")

    def row_formulas(shots_c, sg_c, avg_c, med_c):
        shots_f = sumproduct_formula(sg_c, shots_col=shots_c)
        sg_f    = sumproduct_formula(sg_c)
        # avg = sg_total / shots
        j_col = f"J2:J{n+1}"; k_col = f"K2:K{n+1}"
        sg_r  = f"{sg_c}2:{sg_c}{n+1}"; sh_r = f"{shots_c}2:{shots_c}{n+1}"
        match = f'(({j_col}=A5)*(($A$2=0)+($A$2>0)*({k_col}<=$A$2)))'
        avg_f = (f'=IFERROR(ROUND(SUMPRODUCT({match}*IFERROR({sg_r},0))'
                 f'/SUMPRODUCT({match}*IFERROR({sh_r},0)),3),"")')
        med_f = med_formula(med_c, shots_c)
        est_f = est_formula(med_c, shots_c)
        return [shots_f, sg_f, avg_f, med_f, est_f]

    # ── Assemble the tab content ───────────────────────────────────────────────
    # Row 1:  "Last X Rounds" label
    # Row 2:  filter value (default 0 = all)  — user edits A2
    # Row 3:  blank
    # Row 4:  "Benchmark" label
    # Row 5:  filter value (default "Tour")   — user edits A5
    # Row 6:  blank
    # Row 7:  column headers
    # Rows 8-11: category rows (with conditional formatting)
    # Row 12: Total row (bold, no conditional formatting)

    COL_HEADER = ["Category", "Total Shots", "Total SG", "Avg / Shot",
                  "Median / Shot", "Est. Impact"]

    tab_rows = [
        ["Last X Rounds", "", "", "", "", ""],           # row 1  (A1)
        [0,               "", "", "", "", ""],           # row 2  (A2 = filter value)
        ["",              "", "", "", "", ""],           # row 3
        ["Benchmark",     "", "", "", "", ""],           # row 4  (A4)
        [PROFILE_DISPLAY["tour"], "", "", "", "", ""],   # row 5  (A5 = filter value)
        ["",              "", "", "", "", ""],           # row 6
        COL_HEADER,                                      # row 7  (col headers)
    ]

    cat_data_start = len(tab_rows)  # 0-indexed row 7 = 8th row

    for label, sc, sg_c, av_c, md_c in CAT_COLS:
        tab_rows.append([label] + row_formulas(sc, sg_c, av_c, md_c))

    # Total row
    sc, sg_c, av_c, md_c = TOT_COLS
    tab_rows.append(["Total"] + row_formulas(sc, sg_c, av_c, md_c))

    # ── Write everything ──────────────────────────────────────────────────────
    overwrite_tab(service, sid, BREAKDOWN_TAB, tab_rows)

    # Write helper data starting at H1
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"'{BREAKDOWN_TAB}'!H1",
        valueInputOption="USER_ENTERED",
        body={"values": helper_data},
    ).execute()

    # ── Bold: row 1 (label), row 4 (label), row 7 (col headers), row 12 (Total)
    bold_rows_idx = [0, 3, 6, cat_data_start + 4]
    bold_cells(service, sid, sheet_id, bold_rows_idx, col_start=0, col_end=6)

    # ── Conditional formatting: category rows only (rows 8-11), cols 2-5 (0-indexed)
    clear_conditional_formats(service, sid, sheet_id)
    add_gradient(service, sid, sheet_id,
                 cat_data_start,           # first category row
                 cat_data_start + 3,       # last category row (4 cats)
                 [2, 3, 4, 5])             # Total SG, Avg, Median, Est. Impact

    print(f"  '{BREAKDOWN_TAB}': written with {n} data rows in helper range")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if not GSHEETS_AVAILABLE:
        sys.exit(1)
    if not GOOGLE_SHEET_ID or GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
        print("❌  Set GOOGLE_SHEET_ID in config.py or as env var GOOGLE_SHEET_ID")
        sys.exit(1)
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌  Missing {GOOGLE_CREDENTIALS_FILE} — download from Google Cloud Console")
        sys.exit(1)

    print("Authenticating with Google Sheets…")
    service = get_service()
    print(f"Uploading to: {GOOGLE_SHEET_ID}")

    upload_scorecard(service, GOOGLE_SHEET_ID)
    upload_shot_detail(service, GOOGLE_SHEET_ID)
    upload_strokes_gained(service, GOOGLE_SHEET_ID)
    upload_breakdown(service, GOOGLE_SHEET_ID)

    print("✅  Upload complete.")


if __name__ == "__main__":
    main()
