import unittest
from unittest.mock import Mock, patch

from leadbot.core.models import Lead
from leadbot.core.scoring import LeadScorer
from leadbot.enrichment.website_discovery import discover_website


class V4ScoringTests(unittest.TestCase):
    def setUp(self):
        self.scorer = LeadScorer()

    def test_scores_are_separate(self):
        result = self.scorer.score_lead({
            "name": "Care Clinic",
            "niche": "clinic",
            "website": "https://care.example",
            "website_status": "200",
            "phone": "+15551234567",
            "email": "hello@care.example",
            "social_links": "https://instagram.com/care",
            "location": "Austin, Texas",
            "source_url": "osm://1",
        })
        self.assertEqual(result["contactability_score"], 100)
        self.assertEqual(result["contactability_tier"], "A - Multi-channel")
        self.assertTrue(result["is_contactable"])
        self.assertGreaterEqual(result["lead_quality_score"], 70)
        self.assertGreaterEqual(result["sales_priority_score"], 80)
        self.assertEqual(result["sales_priority"], "Hot")

    def test_social_only_is_contactable_but_not_multi_channel(self):
        result = self.scorer.score_lead({
            "name": "Good Eats",
            "niche": "restaurant",
            "social_links": "https://instagram.com/good",
            "location": "Austin, Texas",
        })
        self.assertEqual(result["contactability_score"], 20)
        self.assertEqual(result["contactability_tier"], "C - Social contact")
        self.assertTrue(result["is_contactable"])

    def test_no_contact_does_not_destroy_lead_quality(self):
        result = self.scorer.score_lead({
            "name": "Care Clinic",
            "niche": "clinic",
            "website": "https://care.example",
            "website_status": "200",
            "location": "Austin, Texas",
            "source_url": "osm://1",
        })
        self.assertEqual(result["contactability_score"], 0)
        self.assertGreaterEqual(result["lead_quality_score"], 70)
        self.assertEqual(result["recommended_offer"], "Enrichment Required")


class WebsiteDiscoveryTests(unittest.TestCase):
    def test_accepts_identity_validated_candidate(self):
        lead = Lead(name="Care Clinic", niche="clinic", location="Austin, Texas")
        guard = Mock()
        guard.allowed.return_value = True
        guard.user_agent = "LeadBot/Test"
        guard.wait.return_value = None

        search_html = '''
        <div class="result">
          <a class="result__a" href="https://careclinic.example/">Care Clinic Austin</a>
          <a class="result__snippet">Care Clinic Austin, Texas</a>
        </div>'''
        page_html = "<html><head><title>Care Clinic Austin Texas</title></head><body>Care Clinic Austin Texas clinic</body></html>"

        class Response:
            status_code = 200
            text = search_html

        class PageResponse:
            status_code = 200
            text = page_html

        with patch("leadbot.enrichment.website_discovery.requests.get", side_effect=[Response(), Response(), PageResponse()]):
            self.assertTrue(discover_website(lead, guard, min_confidence=0.50, max_results=2))

        self.assertEqual(lead.website, "https://careclinic.example/")
        self.assertIn("website_discovery_verified", lead.enrichment_stage)


if __name__ == "__main__":
    unittest.main()
