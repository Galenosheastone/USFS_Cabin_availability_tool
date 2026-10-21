"""Cabin Finder: interactive, on-demand Recreation.gov availability dashboard.

Launch: python -m streamlit run FS_Cabin_App/dashboard.py
Live checks are manual and saved separately from email alert history.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st
import yaml

from availability_service import (
    AccessBlocked, AvailabilityError, load_dashboard_snapshot,
    matching_windows, months_between, save_dashboard_snapshot,
    scan_availability,
)

HERE = Path(__file__).resolve().parent
CACHE_PATH = HERE / "dashboard_state.json"
TODAY = date.today()
LAST_ALLOWED = TODAY + timedelta(days=365)

st.set_page_config(page_title="Montana Cabin Finder", page_icon="🏔️", layout="wide")
st.title("🏔️ Montana Cabin Finder")
st.caption("Find an open Forest Service cabin · Check fresh dates directly against Recreation.gov")

try:
    config = yaml.safe_load((HERE / "config.yaml").read_text())
    cabins = config["campgrounds"]
    snapshot = load_dashboard_snapshot(CACHE_PATH)
except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
    st.error(f"Unable to load cabin configuration or saved results: {exc}")
    st.stop()

names = {str(c["id"]): str(c.get("name", c["id"])) for c in cabins}
id_by_name = {name: cg_id for cg_id, name in names.items()}
forests = sorted({str(c.get("forest", "Uncategorized")) for c in cabins})
districts_by_forest = {
    forest: sorted({str(c.get("district", "Unassigned")) for c in cabins
                    if c.get("forest", "Uncategorized") == forest})
    for forest in forests
}

with st.sidebar:
    st.header("Find a cabin")
    mode = st.radio("Search for", ["Flexible dates", "Exact stay"], horizontal=True)
    checkin = st.date_input("Check-in / earliest arrival", TODAY,
                            min_value=TODAY, max_value=LAST_ALLOWED)
    checkout = st.date_input("Checkout / latest departure", TODAY + timedelta(days=30),
                             min_value=TODAY + timedelta(days=1),
                             max_value=LAST_ALLOWED + timedelta(days=1))
    if mode == "Flexible dates":
        min_nights = st.slider("Minimum consecutive nights", 1, 14, 2)
        weekends = st.checkbox("Include a Friday or Saturday night", value=False)
    else:
        min_nights = (checkout - checkin).days
        weekends = False
        st.caption("Exact stay requires every night from check-in through the day before checkout.")
    forest_choice = st.selectbox(
        "National forest", ["All tracked forests"] + forests,
        index=(forests.index("Custer Gallatin National Forest") + 1)
              if "Custer Gallatin National Forest" in forests else 0,
    )
    eligible_forests = forests if forest_choice == "All tracked forests" else [forest_choice]
    district_choices = sorted({
        f"{forest} / {district}"
        for forest in eligible_forests for district in districts_by_forest[forest]
    })
    chosen_districts = st.multiselect(
        "Ranger districts (blank = all in selected forests)", district_choices
    )
    district_pairs = set(chosen_districts)
    district_cabins = [
        c for c in cabins
        if c.get("forest", "Uncategorized") in eligible_forests
        and (not chosen_districts or f"{c.get('forest', 'Uncategorized')} / {c.get('district', 'Unassigned')}" in district_pairs)
    ]
    district_names = {str(c["id"]): c.get("name", str(c["id"])) for c in district_cabins}
    chosen_names = st.multiselect("Cabins (blank = all in selected districts)", sorted(district_names.values()))
    target_ids = ({str(c["id"]) for c in district_cabins if c.get("name", str(c["id"])) in chosen_names}
                  if chosen_names else {str(c["id"]) for c in district_cabins})
    selected_cabins = [c for c in district_cabins if str(c["id"]) in target_ids]
    st.caption("All means all cabins in this curated catalog, not every USFS rental in Montana.")
    valid_dates = checkout > checkin
    if not valid_dates:
        st.error("Checkout must be after check-in.")
    if not selected_cabins:
        st.warning("No cabins match these forests and districts.")
    nights_end = checkout - timedelta(days=1)
    request_count = len(selected_cabins) * len(months_between(checkin, nights_end)) if valid_dates else 0
    st.caption(f"{len(selected_cabins)} tracked cabins · {request_count} monthly API requests")
    scan_pressed = st.button("🔄 Check availability now", type="primary",
                             use_container_width=True, disabled=not valid_dates or not selected_cabins)
    st.caption("Changing filters updates the saved results immediately. Use Check availability now to retrieve new dates.")

if scan_pressed:
    progress_bar = st.progress(0, text="Starting availability check...")
    def on_progress(completed: int, total: int, name: str) -> None:
        progress_bar.progress(completed / total, text=f"Checking {name} · {completed}/{total} requests")
    try:
        new_snapshot = scan_availability(selected_cabins, checkin, nights_end, progress=on_progress)
        save_dashboard_snapshot(CACHE_PATH, new_snapshot)
        st.success(f"Checked {new_snapshot['months_checked']} monthly inventories. Results updated.")
        snapshot = new_snapshot
    except (AccessBlocked, AvailabilityError, OSError, ValueError) as exc:
        st.error(f"Live availability check failed: {exc}. Previously saved results were preserved.")
    finally:
        progress_bar.empty()

if not valid_dates:
    st.info("Select a checkout date after the check-in date.")
    st.stop()

st.subheader("Availability results")
if snapshot is None:
    st.info("No current scan saved yet. Choose your cabins and dates, then select **Check availability now**. The old alert history does not contain current availability.")
    st.stop()

saved_ids = set(snapshot.get("requested_ids", []))
saved_start = date.fromisoformat(snapshot["start_date"])
saved_end = date.fromisoformat(snapshot["end_date"])
covered_ids = target_ids & saved_ids
missing_ids = target_ids - saved_ids
date_coverage_complete = saved_start <= checkin and saved_end >= nights_end
is_complete = not missing_ids and date_coverage_complete and not snapshot.get("failures")

checked_at = snapshot.get("checked_at", "unknown")
st.caption(f"Last live check: {checked_at} · Snapshot covers nights {saved_start:%b %d, %Y} – {saved_end:%b %d, %Y}")
try:
    checked_dt = datetime.fromisoformat(checked_at)
    if checked_dt.tzinfo is None:
        checked_dt = checked_dt.astimezone()
    if (datetime.now().astimezone() - checked_dt).total_seconds() > 6 * 3600:
        st.warning("These results are over six hours old. Check again before booking.")
except (TypeError, ValueError):
    st.warning("The age of these results could not be verified. Consider checking again.")

if not date_coverage_complete or missing_ids:
    problems = []
    if not date_coverage_complete:
        problems.append("your selected dates extend outside the saved scan")
    if missing_ids:
        problems.append(f"{len(missing_ids)} selected cabins were not scanned")
    st.warning("Results are incomplete: " + "; ".join(problems) + ". Select **Check availability now** to cover your filters.")
if snapshot.get("failures"):
    st.warning(f"{len(snapshot['failures'])} monthly inventories failed. Those dates are UNKNOWN, not confirmed unavailable.")
    with st.expander("See failed requests"):
        for issue in snapshot["failures"]:
            st.write(f"{names.get(issue['id'], issue['id'])} · {issue['month']}: {issue['error']}")

rows = []
for cg_id in sorted(covered_ids):
    for site_key, days in snapshot.get("availability", {}).get(cg_id, {}).items():
        windows = matching_windows(days, checkin, nights_end, min_nights, weekends)
        for start_day, end_day, available_nights in windows:
            if mode == "Exact stay":
                if start_day > checkin or end_day < checkout:
                    continue
                start_day, end_day, available_nights = checkin, checkout, (checkout - checkin).days
            rows.append({"id": cg_id, "cabin": names[cg_id], "site": site_key.split("||")[0],
                         "start": start_day, "end": end_day, "nights": available_nights})

rows.sort(key=lambda row: (row["start"], row["cabin"], row["site"]))
a, b, c = st.columns(3)
a.metric("Cabins with openings", len({row["id"] for row in rows}))
b.metric("Matching stay windows", len(rows))
c.metric("Earliest check-in", rows[0]["start"].strftime("%b %d") if rows else "—")

if not rows:
    if is_complete:
        st.info("No matching open nights were found in the last scan. Try a shorter stay, different dates, or more cabins.")
    else:
        st.info("No matching openings in the portion successfully checked. Scan your selected dates and cabins to confirm.")
else:
    by_cabin = defaultdict(list)
    for row in rows:
        by_cabin[row["id"]].append(row)
    st.caption("Showing up to four available windows per cabin, sorted by earliest check-in.")
    for cg_id in sorted(by_cabin, key=lambda key: by_cabin[key][0]["start"]):
        items = by_cabin[cg_id]
        with st.container(border=True):
            label_col, book_col = st.columns([4, 1])
            with label_col:
                st.markdown(f"#### {names[cg_id]}")
                st.caption(f"{len(items)} matching stay window(s)")
            with book_col:
                st.link_button("View on Recreation.gov ↗",
                               f"https://www.recreation.gov/camping/campgrounds/{cg_id}",
                               use_container_width=True)
            for item in items[:4]:
                st.markdown(
                    f"📅 **{item['start']:%a, %b %d} → {item['end']:%a, %b %d, %Y}**"
                    f" · {item['nights']} available night(s) · Site {item['site']}"
                )
            if len(items) > 4:
                with st.expander(f"Show {len(items) - 4} more window(s)"):
                    for item in items[4:]:
                        st.write(f"{item['start']:%b %d} – {item['end']:%b %d} · {item['nights']} nights · {item['site']}")

st.caption("Results reflect observed night availability, not a guaranteed reservation. Confirm final prices, rules, and inventory directly on Recreation.gov.")
