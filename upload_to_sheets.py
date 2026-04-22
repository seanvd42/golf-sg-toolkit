"""
upload_to_sheets.py — Step 5
══════════════════════════════
Pushes the generated CSVs into your existing Google Sheet.

Tabs written / updated
──────────────────────
    "Hole by Hole"    ← scorecard.csv rows, appended (won't duplicate)
    "Strokes Gained"  ← sg_summary.csv rows, appended
    "Shot Detail"     ← sg_shots.csv rows, appended (created if absent)

Usage
─────
    python upload_to_sheets.py [data_dir]

    # Default: reads from config.py paths
    python upload_to_sheets.py

Prerequisites
─────────────
1.  pip install google-auth google-auth-oauthlib google-api-python-client

2.  Create a Google Cloud project, enable the Sheets API, and download OAuth2
    credentials as  credentials.json  in this directory.
    Guide: https://developers.google.com/sheets/api/quickstart/python

3.  Set GOOGLE_SHEET_ID in config.py (or as env var).

    The script will open your browser once to authorise; subsequent runs use
    a cached token stored in  token.json.

Duplicate prevention
─────────────────────
Before appending, the script reads existing (round_id, hole_number) pairs
from "Hole by Hole" and skips rows that already exist.
For "Strokes Gained" it keys on (round_id,).
"""

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE,
    SCORECARD_CSV, SG_SUMMARY_CSV, SG_SHOTS_CSV,
    SHEET_HOLE_TAB, SHEET_SG_TAB,
)

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


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_FILE = "token.json"

SHOT_DETAIL_TAB = "Shot Detail"


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

def get_or_create_tab(service, spreadsheet_id: str, tab_name: str) -> str:
    """Return the tab name, creating it if it doesn't exist."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if tab_name not in existing:
        body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
        print(f"  Created tab: {tab_name}")
    return tab_name


def read_tab(service, spreadsheet_id: str, tab_name: str) -> list[list]:
    """Read all values from a tab."""
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'"
    ).execute()
    return result.get("values", [])


def append_rows(service, spreadsheet_id: str, tab_name: str, rows: list[list]):
    """Append rows to the bottom of a tab."""
    body = {"values": rows}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


def ensure_header(service, spreadsheet_id: str, tab_name: str, header: list[str]):
    """Write the header row only if the tab is empty."""
    existing = read_tab(service, spreadsheet_id, tab_name)
    if not existing:
        append_rows(service, spreadsheet_id, tab_name, [header])


# ── per-file upload ───────────────────────────────────────────────────────────

def upload_scorecard(service, spreadsheet_id: str, csv_path: str):
    tab = SHEET_HOLE_TAB
    get_or_create_tab(service, spreadsheet_id, tab)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []

    ensure_header(service, spreadsheet_id, tab, header)

    # Read existing rows to detect duplicates
    existing_data = read_tab(service, spreadsheet_id, tab)
    if len(existing_data) > 1:
        ex_header = existing_data[0]
        try:
            rid_col  = ex_header.index("round_id")
            hole_col = ex_header.index("hole_number")
        except ValueError:
            rid_col, hole_col = 0, 3  # fallback positions
        existing_keys = {
            (r[rid_col], r[hole_col])
            for r in existing_data[1:]
            if len(r) > max(rid_col, hole_col)
        }
    else:
        existing_keys = set()

    new_rows = []
    for row in rows:
        key = (row.get("round_id", ""), row.get("hole_number", ""))
        if key not in existing_keys:
            new_rows.append([row.get(h, "") for h in header])

    if new_rows:
        append_rows(service, spreadsheet_id, tab, new_rows)
        print(f"  '{tab}': appended {len(new_rows)} hole row(s)")
    else:
        print(f"  '{tab}': no new rows (all already present)")


def upload_sg_summary(service, spreadsheet_id: str, csv_path: str):
    tab = SHEET_SG_TAB
    get_or_create_tab(service, spreadsheet_id, tab)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []

    ensure_header(service, spreadsheet_id, tab, header)

    existing_data = read_tab(service, spreadsheet_id, tab)
    existing_rids = set()
    if len(existing_data) > 1:
        ex_header = existing_data[0]
        try:
            rid_col = ex_header.index("round_id")
        except ValueError:
            rid_col = 0
        existing_rids = {r[rid_col] for r in existing_data[1:] if r}

    new_rows = [
        [row.get(h, "") for h in header]
        for row in rows
        if row.get("round_id", "") not in existing_rids
    ]

    if new_rows:
        append_rows(service, spreadsheet_id, tab, new_rows)
        print(f"  '{tab}': appended {len(new_rows)} round summary row(s)")
    else:
        print(f"  '{tab}': no new round summaries")


def upload_shot_detail(service, spreadsheet_id: str, csv_path: str):
    tab = SHOT_DETAIL_TAB
    get_or_create_tab(service, spreadsheet_id, tab)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []

    ensure_header(service, spreadsheet_id, tab, header)

    existing_data = read_tab(service, spreadsheet_id, tab)
    existing_keys = set()
    if len(existing_data) > 1:
        ex_header = existing_data[0]
        try:
            rid_col  = ex_header.index("round_id")
            hole_col = ex_header.index("hole_number")
            shot_col = ex_header.index("shot_number")
        except ValueError:
            rid_col, hole_col, shot_col = 0, 3, 7
        existing_keys = {
            (r[rid_col], r[hole_col], r[shot_col])
            for r in existing_data[1:]
            if len(r) > max(rid_col, hole_col, shot_col)
        }

    new_rows = []
    for row in rows:
        key = (row.get("round_id",""), row.get("hole_number",""), row.get("shot_number",""))
        if key not in existing_keys:
            new_rows.append([row.get(h, "") for h in header])

    if new_rows:
        append_rows(service, spreadsheet_id, tab, new_rows)
        print(f"  '{tab}': appended {len(new_rows)} shot row(s)")
    else:
        print(f"  '{tab}': no new shot rows")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if not GSHEETS_AVAILABLE:
        sys.exit(1)

    if not GOOGLE_SHEET_ID or GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
        print("❌  Set GOOGLE_SHEET_ID in config.py (or as env var) before uploading.")
        sys.exit(1)

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌  Missing {GOOGLE_CREDENTIALS_FILE}.")
        print("   Download OAuth2 credentials from Google Cloud Console → APIs & Services → Credentials.")
        sys.exit(1)

    print("Authenticating with Google Sheets…")
    service = get_service()

    print(f"Uploading to spreadsheet: {GOOGLE_SHEET_ID}")

    if os.path.exists(SCORECARD_CSV):
        upload_scorecard(service, GOOGLE_SHEET_ID, SCORECARD_CSV)
    else:
        print(f"  Skipping scorecard (file not found: {SCORECARD_CSV})")

    if os.path.exists(SG_SUMMARY_CSV):
        upload_sg_summary(service, GOOGLE_SHEET_ID, SG_SUMMARY_CSV)
    else:
        print(f"  Skipping SG summary (file not found: {SG_SUMMARY_CSV})")

    if os.path.exists(SG_SHOTS_CSV):
        upload_shot_detail(service, GOOGLE_SHEET_ID, SG_SHOTS_CSV)
    else:
        print(f"  Skipping shot detail (file not found: {SG_SHOTS_CSV})")

    print("✅  Upload complete.")


if __name__ == "__main__":
    main()
