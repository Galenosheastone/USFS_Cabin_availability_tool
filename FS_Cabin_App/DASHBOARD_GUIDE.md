# Cabin Finder dashboard — selecting areas

Start the dashboard with:

```bash
git pull origin feature/cabin-dashboard-v2
python -m streamlit run FS_Cabin_App/dashboard.py
```

The sidebar now filters in this order:

1. **National forest**: defaults to Custer Gallatin; choose **All tracked forests** to include everything configured.
2. **Ranger districts**: choose one or more districts within your selected forest(s), or leave blank to include all.
3. **Cabins**: optionally narrow down the remaining cabins; blank means all cabins in your selection.
4. **Dates and length of stay**: select dates and either flexible dates or an exact stay.

Click **Check availability now** after changing the area or date window to query Recreation.gov. Adjusting filters only filters data from the last scan. The snapshot is clearly marked incomplete when previously unscanned cabins are selected.

## Coverage and limitations

The catalog currently includes 47 configured cabins across seven Montana national forests and is a **curated list, not a complete Montana or USFS inventory**. District names and newly added campground IDs should be reviewed against current official USFS and Recreation.gov listings; forest/district assignments can change. If a cabin fails to load, consult its Recreation.gov listing and edit `FS_Cabin_App/config.yaml`.

Avoid scanning all tracked cabins over long date ranges frequently: each cabin-month requires a request. The checker does not guarantee reservations or realtime checkout inventory. API failures must not be treated as confirmed unavailability.

**Security:** A Gmail app password appeared in older repository history. Rotate/revoke the old credential before using email notifications.
