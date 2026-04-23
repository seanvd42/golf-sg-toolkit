"""
upload_to_sheets.py — Step 5
══════════════════════════════
Tabs written
────────────
  "Hole by Hole"    ← scorecard.csv   — appended, keyed (round_id, hole_number)
  "Shot Detail"     ← sg_shots.csv    — appended, keyed (round_id, hole, shot)
                      Has sg_tour / sg_scratch / sg_10 / sg_bogey columns
  "Strokes Gained"  ← one block per round × benchmark — overwritten each run
  "Breakdown"       ← formula-driven summary referencing Shot Detail directly
                      A1: "Last X Rounds"   A2: filter value (0=all)
                      A4: "Benchmark"        A5: filter value (Tour/Scratch/…)
                      C7:G7 column headers
                      C8:G11 category rows (conditional formatting)
                      C12: Total row (bold, no conditional formatting)
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

PROFILE_DISPLAY = {
    "tour":    "Tour",
    "scratch": "Scratch",
    "10":      "10 Handicap",
    "bogey":   "Bogey",
}


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
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == name:
            return s["properties"]["sheetId"]
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
        spreadsheetId=sid, range=f"'{name}'!A1",
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
            spreadsheetId=sid, range=f"'{name}'!A1",
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
    for _ in range(30):
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
                        "minpoint": {"colorStyle": {"rgbColor": _color(220, 80,  80)}, "type": "MIN"},
                        "midpoint": {"colorStyle": {"rgbColor": _color(255, 255, 255)}, "type": "NUMBER", "value": "0"},
                        "maxpoint": {"colorStyle": {"rgbColor": _color(80,  180, 80)},  "type": "MAX"},
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
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": r, "endRowIndex": r + 1,
                "startColumnIndex": col_start, "endColumnIndex": col_end,
            },
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }
    } for r in row_indices]
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": requests}
        ).execute()


def hide_columns(service, sid, sheet_id, start_col, end_col):
    """Hide columns start_col..end_col (0-indexed, exclusive end)."""
    service.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId":    sheet_id,
                    "dimension":  "COLUMNS",
                    "startIndex": start_col,
                    "endIndex":   end_col,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        }]},
    ).execute()


# ── upload: Hole by Hole ──────────────────────────────────────────────────────

def upload_scorecard(service, sid):
    if not os.path.exists(SCORECARD_CSV):
        print(f"  Skipping {HOLE_TAB}")
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
        print(f"  '{HOLE_TAB}': appended {len(new)} rows")
    else:
        print(f"  '{HOLE_TAB}': no new rows")


# ── upload: Shot Detail ───────────────────────────────────────────────────────

def upload_shot_detail(service, sid):
    if not os.path.exists(SG_SHOTS_CSV):
        print(f"  Skipping {SHOT_TAB}")
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
        print(f"  '{SHOT_TAB}': appended {len(new)} shots")
    else:
        print(f"  '{SHOT_TAB}': no new shots")


# ── upload: Strokes Gained (per-round blocks) ─────────────────────────────────

def upload_strokes_gained(service, sid):
    if not os.path.exists(SG_SUMMARY_CSV):
        print(f"  Skipping {SG_TAB}")
        return
    sheet_id = get_sheet_id(service, sid, SG_TAB)

    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    profile_order = {p: i for i, p in enumerate(AVAILABLE_PROFILES)}
    all_rows.sort(key=lambda r: (r["round_date"], profile_order.get(r["benchmark_profile"], 99)))

    CATS = [
        ("Drives",         "sg_drives"),
        ("Long Approach",  "sg_long_approach"),
        ("Short Approach", "sg_short_approach"),
        ("Putting",        "sg_putting"),
    ]
    COL_HDR = ["Category", "Total Shots", "Total SG", "Avg / Shot", "Median / Shot", "Per Round"]

    def ff(v):
        try:    return round(float(v), 3)
        except: return ""

    output     = []
    bold_rows  = []
    fmt_ranges = []

    for r in all_rows:
        profile_lbl = PROFILE_DISPLAY.get(r.get("benchmark_profile",""), r.get("benchmark_profile",""))

        bold_rows.append(len(output))
        output.append([
            f"{r['round_date']}  —  {r['course_name']}  [{profile_lbl}]",
            "", "", "", "", ""
        ])
        bold_rows.append(len(output))
        output.append(COL_HDR)

        cat_start = len(output)
        n_rounds  = 1  # this block is one round

        for label, key in CATS:
            shots_all = ff(r.get(f"{key}_shots_all", r.get(f"{key}_shots", 0)))
            total_sg  = ff(r.get(key))
            avg       = ff(r.get(f"{key}_mean_per_shot"))
            median    = ff(r.get(f"{key}_median_per_shot"))
            per_round = total_sg   # per round = total SG (only 1 round per block)
            output.append([label, shots_all, total_sg, avg, median, per_round])

        fmt_ranges.append((cat_start, len(output) - 1))

        # Total row
        t_shots = ff(r.get("sg_total_shots_all", r.get("shots_counted", 0)))
        t_sg    = ff(r.get("sg_total"))
        t_avg   = ff(r.get("sg_total_mean_per_shot"))
        t_med   = ff(r.get("sg_total_median_per_shot"))
        bold_rows.append(len(output))
        output.append(["Total", t_shots, t_sg, t_avg, t_med, t_sg])  # per round = total for 1 round

        output.append([""] * 6)  # spacer

    overwrite_tab(service, sid, SG_TAB, output)
    bold_cells(service, sid, sheet_id, bold_rows, col_start=0, col_end=6)
    clear_conditional_formats(service, sid, sheet_id)
    for start_row, end_row in fmt_ranges:
        add_gradient(service, sid, sheet_id, start_row, end_row, [2, 3, 4, 5])
    print(f"  '{SG_TAB}': wrote {len(all_rows)} block(s)")


# ── upload: Breakdown (formula-driven, references Shot Detail) ────────────────

def upload_breakdown(service, sid):
    """
    Layout:
      A1: "Last X Rounds"   A2: 0  (user edits — 0 = all)
      A4: "Benchmark"       A5: "Tour"  (user edits)
      (A5 valid values: Tour / Scratch / 10 Handicap / Bogey)

      C7:G7  column headers
      C8:G11 category rows  (conditional formatting on cols D-G = indices 3-6)
      C12:G12 Total row     (bold, no conditional formatting)

    Formulas reference 'Shot Detail'!A:U directly.
    Shot Detail column layout (0-indexed):
      0  round_id        8  shot_type       16 sg_category
      1  round_date      9  start_lie       17 sg_tour
      2  course_name     10 start_dist      18 sg_scratch
      3  hole_number     11 end_lie         19 sg_10
      4  par             12 end_dist        20 sg_bogey
      5  hole_yards      13 penalty
      6  hole_handicap   14 (reserved)
      7  shot_number     15 club / sg_category depending on version

    We use named column letters for robustness.
    """
    if not os.path.exists(SG_SHOTS_CSV):
        print(f"  Skipping {BREAKDOWN_TAB}")
        return

    # Find how many data rows are in Shot Detail (need for formula range)
    with open(SG_SHOTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        shot_rows  = list(reader)

    n = len(shot_rows) + 1  # +1 for header; formulas reference row 2 to n+1

    # Determine which columns hold the data we need in Shot Detail
    # We'll reference by header name → column letter mapping
    def col_letter(idx):
        """Convert 0-based column index to A1 letter(s)."""
        result = ""
        while True:
            result = chr(65 + idx % 26) + result
            idx = idx // 26 - 1
            if idx < 0:
                break
        return result

    # Build col letter map from fieldnames
    col = {name: col_letter(i) for i, name in enumerate(fieldnames)}

    # Profile display name → sg column name in Shot Detail
    profile_sg_col = {
        "Tour":        col.get("sg_tour",    "R"),
        "Scratch":     col.get("sg_scratch", "S"),
        "10 Handicap": col.get("sg_10",      "T"),
        "Bogey":       col.get("sg_bogey",   "U"),
    }

    cat_col   = col.get("sg_category", "Q")
    date_col  = col.get("round_date",  "B")

    # Shot Detail tab reference prefix
    SD = f"'{SHOT_TAB}'"

    def _sumif_formula(cat_value, sg_col_letter):
        """
        SUMPRODUCT-based formula:
          - sg_category matches cat_value (or "total" = all categories)
          - round_date ranked within last-N filter (A2)
          - benchmark column matches A5 lookup
        
        For rank filter: we rank rounds newest-first per benchmark.
        Simpler approach: filter by date >= LARGE(unique_dates, A2).
        If A2=0, include all.

        Formula logic:
          match_cat   = (cat_col = cat_value) or cat_value="total"
          match_bench = sg_col determined by A5 (we use CHOOSE/MATCH)
          rank_filter = if A2=0: TRUE, else round_date >= LARGE(date_array, A2)
          result      = SUMPRODUCT(match_cat * rank_filter * sg_vals)
        """
        sg_range   = f"{SD}!{sg_col_letter}2:{sg_col_letter}{n+1}"
        cat_range  = f"{SD}!{cat_col}2:{cat_col}{n+1}"
        date_range = f"{SD}!{date_col}2:{date_col}{n+1}"

        if cat_value == "total":
            cat_match = f'(ISNUMBER({sg_range}))'
        else:
            cat_match = f'({cat_range}="{cat_value}")'

        # Rank filter: include row if A2=0 OR round_date >= Nth largest date
        # LARGE on text dates works in Sheets because ISO dates sort correctly
        rank_filter = (
            f'(($A$2=0)+(($A$2>0)*({date_range}>='
            f'IFERROR(LARGE(IF({cat_range}="{cat_value}",{date_range}),ROUNDUP('
            f'SUMPRODUCT(({cat_range}="{cat_value}")*1)/18*$A$2,0)),""))))'
            if cat_value != "total" else
            f'(($A$2=0)+(($A$2>0)*({date_range}>='
            f'IFERROR(LARGE({date_range},$A$2*18),""))))'
        )

        return (
            f'=IFERROR(ROUND(SUMPRODUCT('
            f'{cat_match}*{rank_filter}*'
            f'IFERROR({sg_range}*1,0)),3),"")'
        )

    def _shots_formula(cat_value):
        """Count non-empty sg values for category (= shots with valid SG)."""
        # We count rows where sg_tour is non-empty (proxy for valid shot)
        # and category matches
        sg_range   = f"{SD}!{col.get('sg_tour','R')}2:{col.get('sg_tour','R')}{n+1}"
        cat_range  = f"{SD}!{cat_col}2:{cat_col}{n+1}"
        date_range = f"{SD}!{date_col}2:{date_col}{n+1}"

        if cat_value == "total":
            cat_match = f'(ISNUMBER({sg_range}))'
        else:
            cat_match = f'({cat_range}="{cat_value}")'

        rank_filter = (
            f'(($A$2=0)+(($A$2>0)*({date_range}>='
            f'IFERROR(LARGE(IF({cat_range}="{cat_value}",{date_range}),ROUNDUP('
            f'SUMPRODUCT(({cat_range}="{cat_value}")*1)/18*$A$2,0)),""))))'
            if cat_value != "total" else
            f'(($A$2=0)+(($A$2>0)*({date_range}>=IFERROR(LARGE({date_range},$A$2*18),""))))'
        )
        return (
            f'=IFERROR(SUMPRODUCT({cat_match}*{rank_filter}*'
            f'ISNUMBER({sg_range})*1),"")'
        )

    def _avg_formula(cat_value, sg_col_letter):
        """SG total / shots count = avg per shot."""
        return (
            f'=IFERROR(ROUND({_sumif_formula(cat_value, sg_col_letter).lstrip("=")}/'
            f'{_shots_formula(cat_value).lstrip("=")},3),"")'
        )

    def _rounds_formula(cat_value):
        """Count distinct round_dates matching filter."""
        date_range = f"{SD}!{date_col}2:{date_col}{n+1}"
        cat_range  = f"{SD}!{cat_col}2:{cat_col}{n+1}"
        sg_range   = f"{SD}!{col.get('sg_tour','R')}2:{col.get('sg_tour','R')}{n+1}"
        rank_filter = (
            f'(($A$2=0)+(($A$2>0)*({date_range}>='
            f'IFERROR(LARGE(IF({cat_range}="{cat_value}",{date_range}),ROUNDUP('
            f'SUMPRODUCT(({cat_range}="{cat_value}")*1)/18*$A$2,0)),""))))'
            if cat_value != "total" else
            f'(($A$2=0)+(($A$2>0)*({date_range}>=IFERROR(LARGE({date_range},$A$2*18),""))))'
        )
        if cat_value == "total":
            cat_match = f'(ISNUMBER({sg_range}))'
        else:
            cat_match = f'({cat_range}="{cat_value}")'
        # SUMPRODUCT(1/COUNTIF) trick for distinct count — use unique dates matching filter
        return (
            f'=IFERROR(SUMPRODUCT({cat_match}*{rank_filter}*'
            f'(1/COUNTIF({date_range},{date_range}))),"")'
        )

    def _per_round_formula(cat_value, sg_col_letter):
        """Total SG / number of rounds = SG per round in this category."""
        total_f  = _sumif_formula(cat_value, sg_col_letter).lstrip("=")
        rounds_f = _rounds_formula(cat_value).lstrip("=")
        return f'=IFERROR(ROUND(({total_f})/({rounds_f}),3),"")'

    def _sg_col_formula(sg_col_letter):
        """
        Wrap the base formula to dynamically select the right sg column based on A5.
        We use CHOOSE(MATCH(A5,...)) to pick the right column.
        Since formulas can't select column letters dynamically, we use:
          =IFERROR(CHOOSE(MATCH(A5,{"Tour","Scratch","10 Handicap","Bogey"},0),
              <tour_formula>, <scratch_formula>, <10_formula>, <bogey_formula>), "")
        """
        return None  # handled inline — we write separate formulas per profile and use CHOOSE

    # Because Sheets formulas can't dynamically pick a column by name, we use
    # CHOOSE(MATCH($A$5,{profiles},0), f_tour, f_scratch, f_10, f_bogey) for each cell.
    PROFILE_LABELS_LIST = ["Tour", "Scratch", "10 Handicap", "Bogey"]
    PROFILE_SG_LETTERS = [
        col.get("sg_tour",    "R"),
        col.get("sg_scratch", "S"),
        col.get("sg_10",      "T"),
        col.get("sg_bogey",   "U"),
    ]

    def choose_formula(cat_value, formula_fn, *extra_args):
        """
        Build CHOOSE(MATCH(A5,...), f_tour, f_scratch, f_10, f_bogey).
        formula_fn(cat_value, sg_col_letter) → formula string (with = prefix).
        """
        parts = []
        for sg_ltr in PROFILE_SG_LETTERS:
            f = formula_fn(cat_value, sg_ltr)
            # Strip outer =IFERROR( ... ,"") wrapper to nest inside CHOOSE
            inner = f.lstrip("=")
            parts.append(inner)
        labels_str = '","'.join(PROFILE_LABELS_LIST)
        return (
            f'=IFERROR(CHOOSE(MATCH($A$5,{{"{labels_str}"}},0),'
            f'{",".join(parts)}),"")'
        )

    def shots_choose(cat_value):
        """Shots count doesn't depend on profile — just return the formula."""
        return _shots_formula(cat_value)

    def avg_choose(cat_value):
        total_choose = choose_formula(cat_value, _sumif_formula).lstrip("=")
        shots_f      = _shots_formula(cat_value).lstrip("=")
        return f'=IFERROR(ROUND(({total_choose})/({shots_f}),3),"")'

    def per_round_choose(cat_value):
        total_choose  = choose_formula(cat_value, _sumif_formula).lstrip("=")
        rounds_f      = _rounds_formula(cat_value).lstrip("=")
        return f'=IFERROR(ROUND(({total_choose})/({rounds_f}),3),"")'

    # ── Build tab rows ────────────────────────────────────────────────────────
    # Columns: A B C D E F G
    #          filters | Category | Total Shots | Total SG | Avg/Shot | Median/Shot | Per Round
    # Filter labels in A; values in A (below label)
    # Table starts at C

    BLANK = ["", "", "", "", "", "", ""]

    tab_rows = [
        ["Last X Rounds", "", "", "", "", "", ""],      # A1
        [0,               "", "", "", "", "", ""],      # A2  ← user edits
        ["",              "", "", "", "", "", ""],      # A3
        ["Benchmark",     "", "", "", "", "", ""],      # A4
        [PROFILE_DISPLAY["tour"], "", "", "", "", "", ""],  # A5  ← user edits
        ["",              "", "", "", "", "", ""],      # A6
        ["", "", "Category", "Total Shots", "Total SG",
         "Avg / Shot", "Median / Shot", "Per Round"],  # Row 7 — col headers (A-H)
    ]

    # Note: we now have 8 columns (A-H) since category is C and data is D-H
    # Adjust BLANK
    BLANK8 = [""] * 8

    # Fix previous rows to 8 cols
    tab_rows = [r + [""] * (8 - len(r)) for r in tab_rows]

    cat_data_start = len(tab_rows)  # 0-indexed row 7

    CAT_DEFS = [
        ("Drives",         "drives"),
        ("Long Approach",  "long_approach"),
        ("Short Approach", "short_approach"),
        ("Putting",        "putting"),
    ]

    # Median requires the summary data since it's not easily computable
    # from raw shots via SUMPRODUCT. We write it from sg_summary.csv using
    # a VLOOKUP approach — write a helper range in column J+ with
    # (profile, category, n_rounds_key, median_value) then VLOOKUP.
    # Simpler: just hardcode from summary data via AVERAGEIFS as approximation.
    # BEST approach: include median in the Shot Detail tab isn't feasible via formula.
    # → We write median as a static CHOOSE that picks from per-round median averages
    #   stored in a small hidden helper block (cols J-M, rows 2-5 per profile).

    # Build helper data: for each profile × category: weighted median across rounds
    import statistics as _stats
    with open(SG_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        summary_rows = list(csv.DictReader(f))

    def weighted_median(profile_key, cat_key):
        rows = [r for r in summary_rows if r["benchmark_profile"] == profile_key]
        if not rows:
            return ""
        pairs = []
        for r in rows:
            med = r.get(f"sg_{cat_key}_median_per_shot","")
            shots = r.get(f"sg_{cat_key}_shots", 0)
            try:
                pairs.append((float(med), int(float(shots))))
            except (ValueError, TypeError):
                pass
        if not pairs:
            return ""
        total_w = sum(w for _, w in pairs)
        if total_w == 0:
            return ""
        wmed = sum(v * w for v, w in pairs) / total_w
        return round(wmed, 3)

    # Helper block at J2: rows = profiles, cols = categories + total
    # J2:N6 — profile × (drives, long_approach, short_approach, putting, total)
    # Row order matches AVAILABLE_PROFILES; col order matches CAT_DEFS + total
    helper_cat_keys = ["drives", "long_approach", "short_approach", "putting", "total"]
    helper_data = [[""] + helper_cat_keys]  # header row J1
    for p in AVAILABLE_PROFILES:
        row = [PROFILE_DISPLAY[p]]
        for ck in helper_cat_keys:
            row.append(weighted_median(p, ck))
        helper_data.append(row)

    def median_formula(cat_idx_0based):
        """
        VLOOKUP into helper block at J:N.
        J col = col 9 (0-indexed); data cols K-O = cat indices 1-5.
        """
        # MATCH(A5, J2:J5, 0) gives row offset; INDEX picks the right cat col
        # Helper range: J2:O5 (profiles=rows, categories=cols)
        # cat_idx_0based: 0=drives,1=long,2=short,3=putting,4=total
        return (
            f'=IFERROR(INDEX(K2:O5,'
            f'MATCH($A$5,J2:J5,0),'
            f'{cat_idx_0based + 1}),"")'
        )

    for i, (label, cat_key) in enumerate(CAT_DEFS):
        row = [
            "", "",                                # A, B empty
            label,                                 # C: category
            shots_choose(cat_key),                 # D: total shots
            choose_formula(cat_key, _sumif_formula),  # E: total SG
            avg_choose(cat_key),                   # F: avg/shot
            median_formula(i),                     # G: median/shot
            per_round_choose(cat_key),             # H: per round
        ]
        tab_rows.append(row)

    # Total row
    total_row = [
        "", "",
        "Total",
        shots_choose("total"),
        choose_formula("total", _sumif_formula),
        avg_choose("total"),
        median_formula(4),
        per_round_choose("total"),
    ]
    tab_rows.append(total_row)

    # Write tab
    overwrite_tab(service, sid, BREAKDOWN_TAB, tab_rows)

    # Write helper data at J1
    sheet_id = get_sheet_id(service, sid, BREAKDOWN_TAB)
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"'{BREAKDOWN_TAB}'!J1",
        valueInputOption="USER_ENTERED",
        body={"values": helper_data},
    ).execute()

    # Bold: row 0 (A1 label), row 3 (A4 label), row 6 (col headers), last data row (Total)
    total_row_idx = cat_data_start + 4
    bold_cells(service, sid, sheet_id,
               [0, 3, 6, total_row_idx],
               col_start=0, col_end=8)

    # Conditional formatting: category rows only (cat_data_start to cat_data_start+3)
    # Cols D-H = indices 3-7 (Total SG, Avg/Shot, Median/Shot, Per Round)
    clear_conditional_formats(service, sid, sheet_id)
    add_gradient(service, sid, sheet_id,
                 cat_data_start, cat_data_start + 3,
                 [4, 5, 6, 7])  # E=Total SG, F=Avg, G=Median, H=Per Round

    # Hide helper columns J-O
    hide_columns(service, sid, sheet_id, 9, 15)

    print(f"  '{BREAKDOWN_TAB}': written")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if not GSHEETS_AVAILABLE:
        sys.exit(1)
    if not GOOGLE_SHEET_ID or GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
        print("❌  Set GOOGLE_SHEET_ID in config.py or as env var GOOGLE_SHEET_ID")
        sys.exit(1)
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌  Missing {GOOGLE_CREDENTIALS_FILE}")
        sys.exit(1)

    print("Authenticating…")
    service = get_service()
    print(f"Uploading to: {GOOGLE_SHEET_ID}")

    upload_scorecard(service, GOOGLE_SHEET_ID)
    upload_shot_detail(service, GOOGLE_SHEET_ID)
    upload_strokes_gained(service, GOOGLE_SHEET_ID)
    upload_breakdown(service, GOOGLE_SHEET_ID)

    print("✅  Upload complete.")


if __name__ == "__main__":
    main()
