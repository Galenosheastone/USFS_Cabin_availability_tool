"""Montana federal rental-cabin discovery through the official RIDB facilities API.

RIDB requires a free API key (RIDB_API_KEY). The scan walks the full Montana facility
inventory, not just a few keyword search results, and flags truncation/errors.
Not every USFS cabin is bookable or present in RIDB; manual entries are retained.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import tempfile
import time

import requests

RIDB_URL = "https://ridb.recreation.gov/api/v1/facilities"
PAGE_SIZE = 50
MAX_PAGES = 500
RENTAL_WORDS = re.compile(
    r"\b(cabins?|lookouts?|guard stations?|ranger stations?|yurts?|bunkhouses?|"
    r"chalets?|lodges?|huts?|rental houses?)\b", re.IGNORECASE
)
NON_RENTAL = re.compile(r"\b(trailheads?|picnic areas?|boat launches?|visitor centers?)\b", re.IGNORECASE)
FORESTS = (
    "Custer Gallatin", "Beaverhead-Deerlodge", "Helena-Lewis and Clark",
    "Flathead", "Lolo", "Kootenai", "Bitterroot", "Nez Perce-Clearwater",
    "Idaho Panhandle", "Caribou-Targhee", "Shoshone",
)


class CatalogError(RuntimeError):
    """Catalog fetching failed; keep the last valid catalog."""


def _usable(record: dict) -> bool:
    name = str(record.get("FacilityName") or "")
    kind = str(record.get("FacilityTypeDescription") or "")
    if not record.get("FacilityID") or not name:
        return False
    if str(record.get("Reservable", "")).strip().lower() in ("false", "no", "0"):
        return False
    if str(record.get("Enabled", "")).strip().lower() in ("false", "no", "0"):
        return False
    if NON_RENTAL.search(name):
        return False
    if not (RENTAL_WORDS.search(name) or RENTAL_WORDS.search(kind)):
        return False
    # The state query is authoritative when coordinates or address data are missing.
    lat, lon = record.get("FacilityLatitude"), record.get("FacilityLongitude")
    try:
        if lat not in (None, "", 0, "0") and lon not in (None, "", 0, "0"):
            if not (44.0 <= float(lat) <= 49.1 and -116.3 <= float(lon) <= -104.0):
                return False
    except (TypeError, ValueError):
        pass
    return True


def _forest(record: dict) -> str:
    context = " ".join(str(record.get(k) or "") for k in (
        "RecAreaName", "ParentRecAreaName", "FacilityDescription", "FacilityName"
    ))
    for forest in FORESTS:
        if forest.casefold() in context.casefold():
            return forest + " National Forest"
    return "Unassigned Montana federal recreation"


def _district(record: dict) -> str:
    for key in ("RangerDistrict", "DistrictName", "District"):
        value = record.get(key)
        if value and isinstance(value, str):
            return value.strip()
    return "District not identified"


def candidate_from_ridb(record: dict) -> dict | None:
    """Return a normalized candidate, or None for non-cabin/disabled facilities."""
    if not _usable(record):
        return None
    result = {
        "id": str(record["FacilityID"]),
        "name": str(record["FacilityName"]).strip().title()
                if str(record["FacilityName"]).isupper()
                else str(record["FacilityName"]).strip(),
        "forest": _forest(record),
        "district": _district(record),
        "source": "RIDB",
    }
    return result


def discover_montana(api_key: str, session=None, progress=None, page_limit: int = MAX_PAGES) -> dict:
    """Walk every facility in Montana and select likely reservable cabin-like rentals.

    Does not claim every candidate is USFS-operated or guarantees true statewide
    completeness; the authoritative RIDB dataset can omit listings.
    """
    if not api_key or not api_key.strip():
        raise CatalogError("RIDB API key is required.")
    if page_limit < 1:
        raise ValueError("page_limit must be at least one.")
    session = session or requests.Session()
    by_id: dict[str, dict] = {}
    offset = 0
    total = None
    for page in range(page_limit):
        try:
            response = session.get(
                RIDB_URL,
                params={"state": "MT", "limit": PAGE_SIZE, "offset": offset},
                headers={"apikey": api_key, "Accept": "application/json"},
                timeout=(10, 35),
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CatalogError(f"RIDB catalog query failed after {offset} facilities: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("RECDATA"), list):
            raise CatalogError("Unexpected RIDB response format; catalog was not updated.")
        page_records = data["RECDATA"]
        meta = data.get("METADATA") or {}
        results = meta.get("RESULTS") or {}
        if results.get("TOTAL_COUNT") is not None:
            try:
                total = int(results["TOTAL_COUNT"])
            except (ValueError, TypeError):
                raise CatalogError("Invalid RIDB pagination metadata.")
        for record in page_records:
            if isinstance(record, dict):
                candidate = candidate_from_ridb(record)
                if candidate:
                    by_id[candidate["id"]] = candidate
        offset += len(page_records)
        if progress:
            progress(offset, total, len(by_id))
        if (total is not None and offset >= total) or len(page_records) < PAGE_SIZE:
            return {
                "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "facility_records_checked": offset,
                "ridb_total_count": total,
                "items": sorted(by_id.values(), key=lambda c: c["name"].casefold()),
                "scope": "Likely reservable cabin-like RIDB facilities located in Montana; manual verification required.",
            }
        if not page_records:
            break
        time.sleep(0.12)
    raise CatalogError(
        f"Stopped after {offset} records without reaching the end of the Montana RIDB catalog. "
        "Saved catalog was preserved."
    )


def merge_catalog(manual: list[dict], discovered: dict | None) -> list[dict]:
    """Preserve curated forest/district metadata for known IDs and deduplicate."""
    merged = {str(c["id"]): dict(c) for c in manual}
    if discovered:
        for entry in discovered.get("items", []):
            key = str(entry["id"])
            if key in merged:
                merged[key].setdefault("source", "Curated + RIDB")
            else:
                merged[key] = dict(entry)
    return sorted(merged.values(), key=lambda x: (
        str(x.get("forest", "")), str(x.get("district", "")), str(x.get("name", "")),
    ))


def save_catalog(path: Path, result: dict) -> None:
    """Atomic write, no API key ever written to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                         prefix=".ridb-", delete=False) as handle:
            temp = Path(handle.name)
            json.dump(result, handle, indent=2)
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def load_catalog(path: Path) -> dict | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CatalogError("Saved RIDB catalog is invalid.")
    return data
