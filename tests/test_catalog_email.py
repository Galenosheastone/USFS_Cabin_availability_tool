"""Unit tests for catalog candidate filtering and safe email reports."""
import unittest
from datetime import date
from FS_Cabin_App.catalog_service import candidate_from_ridb, merge_catalog, CatalogError, discover_montana
from FS_Cabin_App.report_email import build_report, validate_recipient

class CatalogEmailTests(unittest.TestCase):
    def test_catalog_merge_keeps_curated_district(self):
        original=[{"id":"5","name":"Cabin","forest":"Custer Gallatin","district":"Bozeman"}]
        discovered={"items":[{"id":"5","name":"Cabin","forest":"Unknown","district":"Unknown"},
                             {"id":"6","name":"Lookout","forest":"Other","district":"Unassigned"}]}
        merged=merge_catalog(original,discovered)
        self.assertEqual(len(merged),2)
        self.assertEqual(next(c for c in merged if c["id"]=="5")["district"],"Bozeman")

    def test_cabin_candidate(self):
        self.assertIsNotNone(candidate_from_ridb({"FacilityID":"23","FacilityName":"MOOSE CABIN",
                              "FacilityLatitude":46.5,"FacilityLongitude":-111.2}))
        self.assertIsNone(candidate_from_ridb({"FacilityID":"23","FacilityName":"Visitor Center",
                             "FacilityLatitude":46.5,"FacilityLongitude":-111.2}))

    def test_empty_key_is_rejected(self):
        with self.assertRaises(CatalogError):
            discover_montana("")

    def test_recipient_validation(self):
        self.assertEqual(validate_recipient("person@example.org"),"person@example.org")
        for text in ["", "bad", "First <person@example.org>", "a@b.org,second@b.org", "a@b.org\nBcc:other@b.org"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_recipient(text)

    def test_summary_contains_booking_links_and_nights(self):
        data={"checked_at":"2026-10-21","failures":[],"availability":{
            "123":{"001||55":["2026-11-06","2026-11-07"]}}}
        subject, text, html=build_report(data,[{"id":"123","name":"Example Cabin"}],
                              date(2026,11,6),date(2026,11,8),2,True,True)
        self.assertIn("1 matching",subject)
        self.assertIn("recreation.gov/camping/campgrounds/123",text)
        self.assertIn("Example Cabin",html)

if __name__=="__main__":
    unittest.main()
