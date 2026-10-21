# Montana catalog sync and email reports

The dashboard contains **47 manually curated cabins** initially. This is **not all Montana cabins**. For broader coverage, it can search the Recreation Information Database (RIDB) for *likely reservable cabin-like facilities* located in Montana and merge these with the curated list. This is a candidate discovery workflow, not a certified, complete inventory of USFS cabins: RIDB records may include other agencies, missing listings, incomplete ranger district metadata, or facilities not actually bookable.

## 1. Obtain an RIDB API key

Visit https://ridb.recreation.gov/ and follow the API/key registration instructions.

On macOS Terminal, before launching the dashboard:

```bash
export RIDB_API_KEY='your_RIDB_key'
python -m streamlit run FS_Cabin_App/dashboard.py
```

In the sidebar, select **Sync Montana rental catalog (RIDB)**. This walks the Montana facility listing page by page, searches for cabin, lookout, guard station, bunkhouse, yurt, chalet and similar names/types, deduplicates IDs, then saves a local `FS_Cabin_App/ridb_catalog.json` for subsequent launches.

Sync *does not* automatically check availability. Choose forest, ranger district, cabins and dates, then press **Check availability now**. RIDB-discovered records with unverified forest or district labels appear under **Unassigned Montana federal recreation / District not identified**. Verify them on Recreation.gov before trusting organizational placement. The scan can still encounter unsupported facility records.

## 2. Configure result emails (separate from automated watcher)

Revoke the Gmail App Password previously published in repository history. Create a new app password and **never commit it**.

Before launching Streamlit in the same Terminal session:

```bash
export CABIN_SMTP_SENDER='your_address@gmail.com'
export CABIN_GMAIL_APP_PASSWORD='your_new_app_password'
python -m streamlit run FS_Cabin_App/dashboard.py
```

To have an email sent **automatically when a fresh scan completes**, select **Email results when scan finishes** in the sidebar and enter the recipient before clicking **Check availability now**. The scan must complete without failed monthly inventories.\n\nYou can also email an existing completed scan manually: expand **Email results to someone**, enter a recipient, and click **Send results email**. The report includes the date range, matched cabin stays, links to Recreation.gov, and the scan timestamp. The app rejects sending if the currently selected cabin/date coverage is incomplete or any saved monthly requests failed.

Email is **opt-in**: enable the scan-completion checkbox for automatic delivery after that scan, or use the manual send button. It does not schedule recurring automatic emails. It does not use or alter the existing alert notification state. The email sender/credentials must be set on the computer hosting Streamlit. Never expose that computer's public Streamlit instance without authentication if enabling SMTP sending; otherwise anyone with access could send mail.

## Operational limits

- RIDB itself cannot guarantee a complete state-wide USFS rental cabin inventory. Cabin definitions vary; some are operated by other agencies or listed only on agency pages.
- An RIDB record's `FacilityID` is a candidate Recreation.gov identifier, not proof that its availability endpoint is supported.
- Sync requires network access and a RIDB API key. A failed/truncated sync leaves previously saved catalog data untouched.
- Keep scans limited to a sensible forest/district/date range so requests do not get throttled.
