import unittest

from leadbot.enrichment.contact_finder import find_contact_page_url
from leadbot.enrichment.extractors import extract_email, extract_phone
from leadbot.enrichment.schema_org import parse_schema_org


class SchemaOrgTests(unittest.TestCase):
    def test_parses_business_json_ld(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Restaurant", "telephone": "+1 555 123 4567",
         "email": "HELLO@care.example", "url": "https://care.example",
         "sameAs": ["https://facebook.com/careclinic"]}
        </script>
        </head><body></body></html>
        """
        data = parse_schema_org(html)
        self.assertEqual(data["phone"], "+1 555 123 4567")
        self.assertEqual(data["email"], "hello@care.example")
        self.assertEqual(data["website"], "https://care.example")
        self.assertEqual(data["social_links"], "https://facebook.com/careclinic")

    def test_parses_graph_arrays_and_contact_points(self):
        html = """
        <script type="application/ld+json">
        {"@graph": [{"@type": ["LocalBusiness"],
                     "contactPoint": {"telephone": "+15551234567"}}]}
        </script>
        """
        data = parse_schema_org(html)
        self.assertEqual(data["phone"], "+15551234567")

    def test_ignores_non_business_and_malformed_data(self):
        article = '<script type="application/ld+json">{"@type": "Article"}</script>'
        malformed = '<script type="application/ld+json">not json at all</script>'
        self.assertEqual(parse_schema_org(article), {})
        self.assertEqual(parse_schema_org(malformed), {})
        self.assertEqual(parse_schema_org("<p>no structured data</p>"), {})


class ContactFinderTests(unittest.TestCase):
    HOMEPAGE = """
    <html><body>
      <a href="https://shop.example/about">About</a>
      <a href="/contact">Contact us</a>
      <a href="https://other.example/contact">External contact</a>
      <a href="/team">Our team</a>
    </body></html>
    """

    def test_prefers_contact_page_over_about(self):
        self.assertEqual(
            find_contact_page_url(self.HOMEPAGE, "https://shop.example/"),
            "https://shop.example/contact",
        )

    def test_ignores_links_to_other_domains(self):
        page = '<a href="https://other.example/contact">Contact</a>'
        self.assertIsNone(find_contact_page_url(page, "https://shop.example/"))

    def test_returns_none_when_no_candidate_exists(self):
        self.assertIsNone(find_contact_page_url("<p>No links</p>", "https://shop.example/"))


class EmailExtractionTests(unittest.TestCase):
    def test_mailto_link_wins_over_visible_text(self):
        html = '<a href="mailto:hello@shop.example">Mail us</a> office@shop.example'
        self.assertEqual(extract_email(html), "hello@shop.example")

    def test_placeholder_addresses_are_filtered_out(self):
        html = "Email noreply@shop.example or office@shop.example"
        self.assertEqual(extract_email(html), "office@shop.example")

    def test_returns_empty_string_without_any_address(self):
        self.assertEqual(extract_email("<p>Call us instead</p>"), "")


class PhoneExtractionTests(unittest.TestCase):
    def test_tel_link_is_normalized(self):
        html = '<a href="tel:+15551234567">Call us</a>'
        self.assertEqual(extract_phone(html, "US"), "+15551234567")

    def test_us_format_number_from_visible_text(self):
        html = "<p>Reach us at (555) 123-4567 today.</p>"
        self.assertEqual(extract_phone(html, "US"), "+15551234567")

    def test_us_regex_is_skipped_for_other_regions(self):
        html = "<p>Reach us at (555) 123-4567 today.</p>"
        self.assertEqual(extract_phone(html, "PK"), "5551234567")


if __name__ == "__main__":
    unittest.main()
