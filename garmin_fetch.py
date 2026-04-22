"""
garmin_fetch.py — Step 1 (Python version)
══════════════════════════════════════════
Fetches golf round data directly from Garmin Connect.

Usage
─────
    python garmin_fetch.py                      # fetch all golf rounds
    python garmin_fetch.py --last 5             # fetch last 5 rounds
    python garmin_fetch.py --activity 12345678  # one specific activity ID
    python garmin_fetch.py --list               # list rounds and exit

Install dependency
──────────────────
    pip install garminconnect garth requests
"""

import json, os, sys, argparse
from pathlib import Path
from getpass import getpass

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
    from garth.exc import GarthHTTPError
except ImportError:
    print("❌  Missing dependency. Run:  pip install garminconnect garth requests")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from config import GARMIN_EMAIL, GARMIN_PASSWORD, DATA_DIR

TOKEN_DIR = Path("~/.garminconnect").expanduser()
_GCS      = "/gcs-golfcommunity/api/v2"


# ── authentication ────────────────────────────────────────────────────────────

def init_api() -> Garmin:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    # Try cached tokens first
    if list(TOKEN_DIR.glob("*.json")):
        for login_args in [str(TOKEN_DIR), None]:
            try:
                garmin = Garmin()
                if login_args:
                    garmin.login(login_args)
                else:
                    garmin.login()
                print("✅  Logged in with cached tokens")
                return garmin
            except TypeError:
                continue
            except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
                print("⚠️  Cached tokens expired — re-authenticating…")
                break

    # Fresh login
    email    = GARMIN_EMAIL    if GARMIN_EMAIL    != "your@email.com" else os.environ.get("EMAIL")
    password = GARMIN_PASSWORD if GARMIN_PASSWORD != "yourpassword"   else os.environ.get("PASSWORD")
    if not email:    email    = input("Garmin email: ").strip()
    if not password: password = getpass("Garmin password: ")

    try:
        try:
            garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            login_result = garmin.login()
        except TypeError:
            garmin = Garmin(email=email, password=password, is_cn=False)
            login_result = garmin.login()

        if isinstance(login_result, tuple):
            result1, result2 = login_result
        else:
            result1, result2 = login_result, None

        if result1 == "needs_mfa":
            mfa_code = input("MFA code (check your phone/email): ").strip()
            garmin.resume_login(result2, mfa_code)

        # Save tokens — attribute name varies by library version
        try:
            garmin.garth.dump(str(TOKEN_DIR))
        except AttributeError:
            try:
                garmin.garth_client.dump(str(TOKEN_DIR))
            except AttributeError:
                import garth as _garth
                _garth.save(str(TOKEN_DIR))

        print("✅  Logged in and tokens cached")
        return garmin

    except GarminConnectAuthenticationError:
        print("❌  Authentication failed — check your email and password")
        sys.exit(1)
    except GarminConnectTooManyRequestsError:
        print("❌  Too many requests — wait a few minutes and try again")
        sys.exit(1)
    except GarminConnectConnectionError as e:
        print(f"❌  Connection error: {e}")
        sys.exit(1)


# ── API helpers ───────────────────────────────────────────────────────────────

def _connectapi(api: Garmin, path: str, **params):
    return api.connectapi(path, params=params)


# ── golf data fetchers ────────────────────────────────────────────────────────

def fetch_golf_activities(api: Garmin, limit: int = 100) -> list[dict]:
    print(f"  Fetching golf activity list (limit={limit})…")
    try:
        activities = api.get_activities_by_date(
            startdate=None, enddate=None, activitytype="golf", limit=limit
        )
        return activities or []
    except Exception as e:
        print(f"  Direct golf filter failed ({e}), searching all activities…")
        all_acts = api.get_activities(0, limit * 3) or []
        return [a for a in all_acts if
                str(a.get("activityType", {}).get("typeKey", "")).lower() == "golf" or
                "golf" in str(a.get("activityName", "")).lower()]


def fetch_scorecard_id(api: Garmin, activity_id: str, activity_date: str) -> tuple[str, str]:
    """
    Resolve a Garmin activity ID → (scorecard_id, course_name).
    
    Strategy:
      1. Match by activityId in scorecard summary list
      2. Fall back to matching by date (YYYY-MM-DD)
      3. Fall back to using activity_id directly as scorecard_id
    """
    try:
        summaries = _connectapi(
            api, f"{_GCS}/scorecard/summary",
            **{"per-page": 100, "user-locale": "en"},
        )
        sc_list = (summaries or {}).get("scorecardSummaries", [])

        # Primary: match by activity ID
        for s in sc_list:
            if str(s.get("activityId")) == str(activity_id):
                return str(s["id"]), s.get("courseName", "")

        # Fallback: match by date
        clean_date = str(activity_date)[:10]
        for s in sc_list:
            if str(s.get("startTime", ""))[:10] == clean_date:
                print(f"    ✓ Matched scorecard by date: {clean_date} → ID {s['id']}")
                return str(s["id"]), s.get("courseName", "")

    except Exception as e:
        print(f"    ⚠️  Scorecard summary lookup failed: {e}")

    # Last resort: use activity_id as scorecard_id (often works)
    print(f"    ⚠️  No scorecard match found — trying activity ID as scorecard ID")
    return str(activity_id), ""


def fetch_scorecard_detail(api: Garmin, scorecard_id: str) -> dict | None:
    """Fetch full scorecard details (hole scores, par, yardage, pin positions, etc.)."""
    try:
        return _connectapi(
            api, f"{_GCS}/scorecard/detail",
            **{"scorecard-ids": scorecard_id, "include-longest-shot-distance": "true"},
        )
    except Exception as e:
        print(f"    ⚠️  Scorecard fetch failed: {e}")
        return None


def fetch_shot_data(api: Garmin, scorecard_id: str, scorecard: dict | None) -> dict:
    """
    Fetch shot-by-shot data hole-by-hole (Garmin requires one request per hole).
    Returns {"holes": [{holeNumber, shots:[...]}, ...]}
    
    Hole list is derived from the scorecard if available, otherwise assumes 18.
    """
    # Extract hole numbers from the scorecard's nested structure
    hole_numbers = list(range(1, 19))  # safe default
    if scorecard:
        sc_details = scorecard.get("scorecardDetails") or []
        inner_sc   = (sc_details[0].get("scorecard") or {}) if sc_details else {}
        holes_data = inner_sc.get("holes") or []
        if holes_data:
            hole_numbers = [h.get("number") or h.get("holeNumber")
                           for h in holes_data if h.get("number") or h.get("holeNumber")]

    all_hole_shots = []
    for hole_num in hole_numbers:
        try:
            result     = _connectapi(
                api, f"{_GCS}/shot/scorecard/{scorecard_id}/hole",
                **{"hole-numbers": hole_num, "image-size": "IMG_730X730"},
            )
            # API returns {"holeShots": [{holeNumber, shots:[...], pinPosition, ...}]}
            hole_shots = (result or {}).get("holeShots", [])
            if hole_shots:
                all_hole_shots.append(hole_shots[0])
        except Exception as e:
            # 400 errors on non-existent holes (e.g. holes 10-18 on a 9-hole round) are expected
            if "400" not in str(e):
                print(f"    ⚠️  Shot fetch failed for hole {hole_num}: {e}")

    return {"holes": all_hole_shots}


def fetch_clubs(api: Garmin, club_ids: list[int]) -> dict:
    """
    Resolve club IDs to names by calling /api/v2/club/{clubId} for each one.

    The /club/user endpoint doesn't exist — the real API is per-club.
    Silently skips any clubs that return errors.
    Returns a dict mapping clubId (int) → club name (str).
    """
    club_map = {}
    if not club_ids:
        return club_map

    print(f"    Resolving {len(club_ids)} club IDs…")
    for cid in club_ids:
        try:
            result = _connectapi(api, f"{_GCS}/club/{cid}")
            if result:
                name = (result.get("name") or result.get("clubName") or
                        result.get("gearTypeName") or result.get("type") or "")
                if name:
                    club_map[int(cid)] = name
        except Exception:
            pass  # Unknown club — shot will show numeric ID

    found = len(club_map)
    print(f"    ✓ Resolved {found}/{len(club_ids)} club names")
    return club_map


def fetch_round_detail(api: Garmin, activity_id: str | int, activity_date: str,
                       activity_name: str = "") -> dict:
    """Fetch full round data for one activity: scorecard + shots + clubs."""
    activity_id = str(activity_id)

    print(f"    Resolving scorecard ID…")
    scorecard_id, course_name_from_sc = fetch_scorecard_id(api, activity_id, activity_date)
    print(f"    Scorecard ID: {scorecard_id}")

    scorecard = fetch_scorecard_detail(api, scorecard_id)
    shots     = fetch_shot_data(api, scorecard_id, scorecard)

    # Collect all unique club IDs from shots, then resolve names
    club_ids = list({
        s["clubId"]
        for h in (shots or {}).get("holes", [])
        for s in h.get("shots", [])
        if s.get("clubId")
    })
    clubs = fetch_clubs(api, club_ids)

    # Prefer activity name from activity list; fall back to scorecard course name
    final_name = activity_name or course_name_from_sc or activity_id

    return {
        "activityId":     activity_id,
        "scorecardId":    scorecard_id,
        "activityName":   final_name,
        "startTimeLocal": "",          # overwritten by main() from activity list
        "scorecard":      scorecard,
        "shots":          shots,
        "clubs":          clubs,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch golf data from Garmin Connect")
    parser.add_argument("--last",     type=int,  metavar="N",  help="Fetch last N rounds")
    parser.add_argument("--activity", type=str,  metavar="ID", help="Fetch one activity by ID")
    parser.add_argument("--list",     action="store_true",     help="List rounds and exit")
    parser.add_argument("--output",   type=str,  default=None, help="Output JSON path")
    args = parser.parse_args()

    output_path = args.output or f"{DATA_DIR}/golf-export.json"
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Connecting to Garmin Connect…")
    api = init_api()

    if args.activity:
        activities = [{"activityId": args.activity, "activityName": "",
                       "startTimeLocal": ""}]
    else:
        limit      = args.last or 100
        activities = fetch_golf_activities(api, limit)
        if args.last:
            activities = activities[:args.last]

    if not activities:
        print("❌  No golf activities found")
        sys.exit(0)

    print(f"\nFound {len(activities)} golf round(s):\n")
    for i, a in enumerate(activities):
        date_str = str(a.get("startTimeLocal") or a.get("beginTimestamp") or "")[:10]
        name     = a.get("activityName") or f"Activity {a.get('activityId')}"
        print(f"  [{i+1:>2}]  {date_str}  {name}  (id={a.get('activityId')})")

    if args.list:
        return

    print()
    all_rounds = []
    for a in activities:
        activity_id   = a.get("activityId")
        activity_name = a.get("activityName", "")
        date_str      = str(a.get("startTimeLocal") or "")[:10]
        print(f"  Fetching: {date_str} — {activity_name} (id={activity_id})")

        detail = fetch_round_detail(api, activity_id, date_str, activity_name)
        detail["startTimeLocal"] = a.get("startTimeLocal") or ""
        all_rounds.append(detail)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_rounds, f, indent=2)

    print(f"\n✅  Saved {len(all_rounds)} round(s) → {output_path}")
    return output_path


if __name__ == "__main__":
    main()
