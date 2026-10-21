"""Streamlit dashboard for browsing saved cabin availability.

Run: streamlit run FS_Cabin_App/dashboard.py
This reads the checker's last saved scan; it does not poll Recreation.gov itself.
"""
from datetime import date, timedelta
from pathlib import Path
import json

import streamlit as st
import yaml

HERE = Path(__file__).resolve().parent
st.set_page_config(page_title="Montana Cabin Finder", page_icon="🏔️", layout="wide")
st.title("🏔️ Montana Cabin Finder")
st.caption("Forest Service cabins and fire lookouts · Availability from your most recent scan")

@st.cache_data(ttl=30)
def load_snapshot():
    config = yaml.safe_load((HERE / "config.yaml").read_text())
    state_file = HERE / config.get("notifications", {}).get("state_file", "state.json")
    if not state_file.exists():
        return config, None
    return config, json.loads(state_file.read_text())

try:
    config, state = load_snapshot()
except (OSError, ValueError, yaml.YAMLError) as exc:
    st.error(f"Unable to read checker data: {exc}")
    st.stop()

if state is None:
    st.info("No saved availability scan yet. Run python FS_Cabin_App/cabin_checker.py --dry-run to check API access; run without --dry-run to save a snapshot.")
    st.stop()

names = {str(c["id"]): c.get("name", str(c["id"])) for c in config["campgrounds"]}
st.caption(f"Last saved scan: {state.get('last_checked') or 'unknown'} · Dates are not guaranteed until confirmed on Recreation.gov.")
with st.sidebar:
    st.header("Find a stay")
    horizon = st.slider("Look ahead (days)", 7, 365, 90, 7)
    minimum = st.slider("Minimum consecutive nights", 1, 14, 2)
    weekends = st.checkbox("Include a Friday or Saturday night")
    selected = st.multiselect("Cabins", sorted(names.values()), default=[])
    st.button("Refresh saved results", on_click=load_snapshot.clear, use_container_width=True)

today = date.today()
cutoff = today + timedelta(days=horizon)

def runs(dates):
    parsed = sorted(set(date.fromisoformat(d) for d in dates if today <= date.fromisoformat(d) <= cutoff))
    if not parsed:
        return []
    chunks = [[parsed[0]]]
    for d in parsed[1:]:
        if d == chunks[-1][-1] + timedelta(days=1):
            chunks[-1].append(d)
        else:
            chunks.append([d])
    return chunks

def matches(dates):
    groups = runs(dates)
    return [group for group in groups if len(group) >= minimum
            and (not weekends or any(d.weekday() in (4, 5) for d in group))]

rows = []
for cg_id, sites in state.get("availability", {}).items():
    name = names.get(cg_id, f"Cabin {cg_id}")
    if selected and name not in selected:
        continue
    for key, dates in sites.items():
        for nights in matches(dates):
            rows.append({"cabin": name, "id": cg_id,
                         "site": key.split("||")[0],
                         "checkin": nights[0], "checkout": nights[-1] + timedelta(days=1),
                         "nights": len(nights)})
rows.sort(key=lambda item: (item["checkin"], item["cabin"]))

a, b, c = st.columns(3)
a.metric("Cabins with matching stays", len(set(r["id"] for r in rows)))
b.metric("Available stay windows", len(rows))
c.metric("Next opening", rows[0]["checkin"].strftime("%b %d") if rows else "—")
st.divider()
if not rows:
    st.info("No matching stays in the saved scan. Try a shorter minimum stay, a wider date range, or refresh the checker.")
else:
    for item in rows:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.subheader(item["cabin"])
                st.write(f"📅 **{item['checkin']:%a, %b %d} – {item['checkout']:%a, %b %d, %Y}** · {item['nights']} nights")
                st.caption(f"Site: {item['site']}")
            with right:
                st.link_button("View & book ↗", f"https://www.recreation.gov/camping/campgrounds/{item['id']}", use_container_width=True)
st.caption("These are observed available nights, not guaranteed bookable reservations; site-specific stay rules and real-time inventory may differ.")
