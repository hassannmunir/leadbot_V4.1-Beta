import unittest

import pandas as pd

from leadbot.core.scoring import LeadScorer


class LeadScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = LeadScorer()

    def test_case_a_clinic_active_full_contact(self):
        result = self.scorer.score_lead({
            "name": "Care Clinic", "niche": "clinic", "website_status": "200",
            "website": "https://care.example", "phone": "+15551234567",
            "email": "hello@care.example", "social_links": "https://instagram.com/care",
            "location": "123 Main Street", "source_url": "https://www.openstreetmap.org/node/1",
        })
        self.assertEqual(result["contactability_score"], 100)
        self.assertEqual(result["contactability_tier"], "A - Multi-channel")
        self.assertGreaterEqual(result["lead_quality_score"], 70)
        self.assertGreaterEqual(result["sales_priority_score"], 80)
        self.assertEqual(result["sales_priority"], "Hot")
        self.assertEqual(result["recommended_offer"], "AI Agent Integration")

    def test_case_b_restaurant_broken_website_phone(self):
        result = self.scorer.score_lead({
            "name": "Good Eats", "niche": "restaurant", "website_status": "404",
            "phone": "+15551234567", "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/2",
        })
        self.assertEqual(result["contactability_score"], 40)
        self.assertEqual(result["contactability_tier"], "B - Direct contact")
        self.assertGreaterEqual(result["lead_quality_score"], 50)
        self.assertEqual(result["recommended_offer"], "Website Rebuild + AI Agent")

    def test_case_c_active_website_without_contact_is_still_high_quality_but_uncontactable(self):
        result = self.scorer.score_lead({
            "name": "No Contact Clinic", "niche": "clinic", "website_status": "200",
            "website": "https://clinic.example", "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/3",
        })
        self.assertEqual(result["contactability_score"], 0)
        self.assertFalse(result["is_contactable"])
        self.assertGreaterEqual(result["lead_quality_score"], 70)
        self.assertEqual(result["recommended_offer"], "Enrichment Required")

    def test_case_d_clinic_without_website_phone_recovered(self):
        result = self.scorer.score_lead({
            "name": "Phone Clinic", "niche": "clinic", "website_status": "no_website_found",
            "phone": "+15551234567", "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/4",
        })
        self.assertEqual(result["contactability_score"], 40)
        self.assertTrue(result["is_contactable"])
        self.assertEqual(result["contactability_tier"], "B - Direct contact")

    def test_dataframe_scoring(self):
        frame = pd.DataFrame([{
            "name": "Clinic Example", "niche": "clinic", "website_status": "200", "website": "https://clinic.example",
            "phone": "+15551234567", "email": "hello@clinic.example",
            "location": "123 Main Street", "source_url": "osm://1",
        }])
        result = self.scorer.score_dataframe(frame)
        self.assertEqual(result.loc[0, "contactability_score"], 80)
        self.assertTrue(result.loc[0, "is_contactable"])
        self.assertEqual(result.loc[0, "sales_priority"], "Hot")
        self.assertEqual(result.loc[0, "recommended_offer"], "AI Agent Integration")


if __name__ == "__main__":
    unittest.main()
