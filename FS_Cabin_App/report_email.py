"""Send one requested scan summary. Authentication comes from environment secrets."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from email.message import EmailMessage
from email.utils import parseaddr
import html
import os
import smtplib
import ssl

from availability_service import matching_windows


def validate_recipient(value: str) -> str:
    recipient = (value or "").strip()
    _, parsed = parseaddr(recipient)
    if (parsed != recipient or recipient.count("@") != 1 or
            any(ch.isspace() for ch in recipient) or len(recipient) > 254 or
            "." not in recipient.rsplit("@", 1)[-1]):
        raise ValueError("Enter a single valid recipient email address.")
    return recipient


def build_report(snapshot: dict, cabins: list[dict], checkin: date, checkout: date,
                 min_nights: int, weekends: bool, exact: bool) -> tuple[str, str, str]:
    names = {str(c["id"]): str(c.get("name", c["id"])) for c in cabins}
    rows = []
    for cg_id, sites in snapshot.get("availability", {}).items():
        if cg_id not in names:
            continue
        for site_key, days in sites.items():
            for start, end, length in matching_windows(
                    days, checkin, checkout, min_nights, weekends):
                if exact:
                    if start > checkin or end < checkout:
                        continue
                    start, end, length = checkin, checkout, (checkout - checkin).days
                rows.append((names[cg_id], cg_id, site_key.split("||")[0], start, end, length))
    rows.sort(key=lambda row: (row[3], row[0]))
    subject = f"Montana Cabin Finder — {len(rows)} matching stay window(s)"
    lines = [subject, f"Search: {checkin.isoformat()} to {checkout.isoformat()} (checkout)",
             f"Scan: {snapshot.get('checked_at', 'unknown')}",
             "Availability can change; verify directly on Recreation.gov.", ""]
    details = []
    for name, cg_id, site, start, end, length in rows:
        url = f"https://www.recreation.gov/camping/campgrounds/{cg_id}"
        lines.append(f"{name} · {start} to {end} · {length} night(s) · site {site}\n{url}")
        details.append("<li><strong>" + html.escape(name) + "</strong>: " +
                       f"{start} to {end} ({length} nights), site " +
                       html.escape(site) + f' — <a href="{url}">View &amp; book</a></li>')
    if not rows:
        lines.append("No matching stay windows in the scanned data.")
        details.append("<li>No matching stay windows in the scanned data.</li>")
    failures = snapshot.get("failures", [])
    if failures:
        lines.append(f"WARNING: {len(failures)} monthly inventories failed; results may be incomplete.")
    page = ("<html><body style='font-family:Arial,sans-serif;max-width:740px;margin:auto'>"
            "<h2>Montana Cabin Finder results</h2>"
            f"<p>Search {checkin} to {checkout} (checkout); {len(rows)} available stay windows.</p>"
            f"<p>Checked: {html.escape(str(snapshot.get('checked_at', 'unknown')))}</p>"
            "<ul>" + "".join(details) + "</ul>" +
            (f"<p><strong>WARNING:</strong> {len(failures)} monthly requests failed. "
             "Results may be incomplete.</p>" if failures else "") +
            "<p>Availability can change; verify on Recreation.gov.</p></body></html>")
    return subject, "\n".join(lines), page


def send_report(recipient: str, subject: str, text_body: str, html_body: str) -> None:
    recipient = validate_recipient(recipient)
    sender = os.getenv("CABIN_SMTP_SENDER", "").strip()
    password = os.getenv("CABIN_GMAIL_APP_PASSWORD", "")
    host = os.getenv("CABIN_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("CABIN_SMTP_PORT", "587"))
    if not sender or not password:
        raise RuntimeError("Configure CABIN_SMTP_SENDER and CABIN_GMAIL_APP_PASSWORD before sending email.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(host, port, timeout=25) as client:
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        client.login(sender, password)
        client.send_message(msg)
