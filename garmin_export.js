/**
 * garmin_export.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Browser bookmarklet that downloads your Garmin Connect golf shot data as JSON.
 *
 * HOW TO USE
 * ──────────
 * Option A – Paste in DevTools console:
 *   1. Sign in to https://connect.garmin.com
 *   2. Open DevTools → Console (F12 / Cmd-Opt-I)
 *   3. Paste this entire script and press Enter
 *   4. A dialog appears; choose the round you want, then click Download
 *
 * Option B – Browser bookmarklet (easier for repeat use):
 *   1. Go to https://caiorss.github.io/bookmarklet-maker/
 *   2. Paste this script into the "Code" box, title it "GC Golf Export"
 *   3. Drag the blue button to your bookmarks bar
 *   4. While on connect.garmin.com, click the bookmark
 *
 * OUTPUT
 * ──────
 * A file named  golf-export-YYYY-MM-DD.json  is downloaded.
 * Pass it to parse_shots.py as the input.
 *
 * WHAT IS DOWNLOADED
 * ──────────────────
 * For each round:
 *   • Scorecard metadata (course, date, par, handicap)
 *   • Hole-by-hole scores
 *   • Shot-by-shot data including:
 *       – club used (if CT10 / auto-detect is on)
 *       – GPS coordinates before & after
 *       – Distance to hole (yards) before & after
 *       – Lie type (tee, fairway, rough, bunker, green, …)
 *
 * NOTE: Garmin does not expose a public API.  This script works by reusing the
 * authenticated session already open in your browser.  It may break if Garmin
 * changes their internal endpoints.  Tested against Garmin Connect Web, 2024-25.
 */

(async function gcExportGolfScores() {
  const BASE = "https://connect.garmin.com";

  // ── helper: fetch JSON with Garmin session cookies ─────────────────────────
  async function gFetch(path, params = {}) {
    const url = new URL(BASE + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString(), { credentials: "include" });
    if (!res.ok) throw new Error(`Garmin fetch failed: ${res.status} ${url}`);
    return res.json();
  }

  // ── 1. List all golf activities ────────────────────────────────────────────
  console.log("Fetching golf activity list…");
  const activities = await gFetch("/proxy/activitylist-service/activities/search/activities", {
    activityType: "golf",
    start: 0,
    limit: 100,
  });

  if (!activities || activities.length === 0) {
    alert("No golf activities found in your Garmin account.");
    return;
  }

  // Build a simple selection dialog
  const options = activities
    .map((a, i) => `${i}: ${a.activityName} — ${a.startTimeLocal?.slice(0, 10) ?? "?"}`)
    .join("\n");

  const choice = prompt(
    `Found ${activities.length} golf round(s).\n\n` +
    `Enter a number to download ONE round, or leave blank to download ALL:\n\n` +
    options
  );

  const selected =
    choice === null
      ? []                                   // user cancelled
      : choice.trim() === ""
        ? activities                         // all rounds
        : [activities[parseInt(choice, 10)]]; // single round

  if (selected.length === 0) {
    alert("Export cancelled.");
    return;
  }

  // ── 2. For each activity, pull scorecard + shot data ──────────────────────
  const allRounds = [];

  for (const activity of selected) {
    const activityId = activity.activityId;
    console.log(`Fetching scorecard for activity ${activityId}…`);

    // Scorecard (hole scores, par, handicap, yardage)
    let scorecard = null;
    try {
      scorecard = await gFetch(`/proxy/golf-service/scorecard/activity/${activityId}`);
    } catch (e) {
      console.warn(`Scorecard fetch failed for ${activityId}:`, e);
    }

    // Shot-by-shot data (requires CT10 or auto-detection)
    let shots = null;
    try {
      shots = await gFetch(`/proxy/golf-service/activity/${activityId}/shots`);
    } catch (e) {
      console.warn(`Shot data fetch failed for ${activityId}:`, e);
    }

    // Club set / gear used
    let clubs = null;
    try {
      clubs = await gFetch(`/proxy/golf-service/activity/${activityId}/clubs`);
    } catch (e) {
      console.warn(`Club data fetch failed for ${activityId}:`, e);
    }

    allRounds.push({
      activityId,
      activityName: activity.activityName,
      startTimeLocal: activity.startTimeLocal,
      scorecard,
      shots,
      clubs,
    });
  }

  // ── 3. Download as JSON ───────────────────────────────────────────────────
  const date = new Date().toISOString().slice(0, 10);
  const filename = `golf-export-${date}.json`;
  const blob = new Blob([JSON.stringify(allRounds, null, 2)], { type: "application/json" });
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: filename,
  });
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  alert(`✅ Downloaded ${selected.length} round(s) to ${filename}`);
})();
