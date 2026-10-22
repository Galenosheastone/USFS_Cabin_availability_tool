"""Read-only Recreation.gov scanning for the dashboard.

Dashboard scans deliberately never modify the alert checker's state.json.
The Recreation.gov endpoint is undocumented and can change; errors are not vacancies.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import json
import os
import random
import tempfile
import time

import requests

API_URL = "https://www.recreation.gov/api/camps/availability/campground/{id}/month"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; CabinFinder/2.0)"}
DELAY_SECONDS = 2.0


class AvailabilityError(RuntimeError):
    """An availability request failed; its dates must not be called unavailable."""


class AccessBlocked(AvailabilityError):
    """Stop scanning on access restrictions or persistent rate limiting."""


def months_between(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("End date precedes start date.")
    result = []
    current = start.replace(day=1)
    while current <= end:
        result.append(current)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def fetch_month(session: requests.Session, campground_id: str, month: date) -> dict:
    url = API_URL.format(id=campground_id)
    params = {"start_date": month.strftime("%Y-%m-01T00:00:00.000Z")}
    for attempt in range(3):
        try:
            response = session.get(url, params=params, headers=HEADERS, timeout=(5, 15))
        except requests.RequestException as exc:
            if attempt == 2:
                raise AvailabilityError(f"Connection failed: {type(exc).__name__}") from exc
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 403:
            raise AccessBlocked("Recreation.gov denied access (HTTP 403).")
        if response.status_code == 429:
            if attempt == 2:
                raise AccessBlocked("Recreation.gov is rate limiting requests (HTTP 429).")
            value = response.headers.get("Retry-After", "")
            try:
                delay = min(30, max(1, int(value)))
            except ValueError:
                delay = 5 * (attempt + 1)
            time.sleep(delay + random.uniform(0, 0.5))
            continue
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AvailabilityError(f"Bad API response (HTTP {response.status_code}).") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("campsites"), dict):
            raise AvailabilityError("Unexpected availability response format.")
        return payload["campsites"]
    raise AvailabilityError("No valid response after retries.")


def parse_month(campsites: dict, start: date, end: date) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for site_id, info in campsites.items():
        if not isinstance(info, dict) or not isinstance(info.get("availabilities"), dict):
            raise AvailabilityError(f"Unexpected campsite format for {site_id}.")
        site_name = str(info.get("site") or site_id)
        key = f"{site_name}||{site_id}"
        for raw_date, status in info["availabilities"].items():
            if status != "Available":
                continue
            try:
                day = date.fromisoformat(raw_date[:10])
            except (TypeError, ValueError):
                raise AvailabilityError("Unexpected date format from API.")
            if start <= day <= end:
                result.setdefault(key, set()).add(day.isoformat())
    return {key: sorted(days) for key, days in result.items()}


def scan_availability(cabins: list[dict], start: date, end: date, progress=None,
                      session: requests.Session | None = None) -> dict:
    """Scan the selected window. Failed months remain explicitly unknown."""
    months = months_between(start, end)
    result = {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "start_date": start.isoformat(), "end_date": end.isoformat(),
              "requested_ids": [str(c["id"]) for c in cabins],
              "availability": {}, "failures": [], "months_checked": 0}
    session = session or requests.Session()
    total = len(cabins) * len(months)
    completed = 0
    consecutive_errors = 0
    for cabin in cabins:
        cg_id = str(cabin["id"])
        combined: dict[str, set[str]] = {}
        for month in months:
            if completed:
                time.sleep(DELAY_SECONDS)
            try:
                month_data = parse_month(fetch_month(session, cg_id, month), start, end)
                for key, dates in month_data.items():
                    combined.setdefault(key, set()).update(dates)
                result["months_checked"] += 1
                consecutive_errors = 0
            except AccessBlocked:
                raise
            except AvailabilityError as exc:
                result["failures"].append({"id": cg_id, "month": month.strftime("%Y-%m"),
                                           "error": str(exc)})
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise AvailabilityError("Multiple consecutive API failures; scan stopped to avoid misleading results.") from exc
            completed += 1
            if progress:
                progress(completed, total, str(cabin.get("name", cg_id)))
        result["availability"][cg_id] = {key: sorted(days) for key, days in combined.items()}
    return result


def matching_windows(days: list[str], start: date, end: date, min_nights: int = 1,
                     weekend_only: bool = False) -> list[tuple[date, date, int]]:
    """Return (check-in, checkout-exclusive, nights) for continuous available stretches."""
    usable = sorted({date.fromisoformat(d) for d in days if start <= date.fromisoformat(d) <= end})
    if not usable:
        return []
    runs = []
    first = last = usable[0]
    for day in usable[1:] + [end + timedelta(days=2)]:
        if day == last + timedelta(days=1):
            last = day
            continue
        stretch = (last - first).days + 1
        if stretch >= min_nights:
            if not weekend_only or any((first + timedelta(days=i)).weekday() in (4, 5)
                                       for i in range(stretch)):
                runs.append((first, last + timedelta(days=1), stretch))
        first = last = day
    return runs


def save_dashboard_snapshot(path: Path, snapshot: dict) -> None:
    """Persist separately from the email-alert deduplication state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".cabin-",
                                         suffix=".tmp", delete=False) as f:
            temp_name = f.name
            json.dump(snapshot, f, indent=2)
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def load_dashboard_snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("availability"), dict):
        raise ValueError("Invalid dashboard snapshot.")
    return data
