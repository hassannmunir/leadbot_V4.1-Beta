"""Tests for the web console templates."""

import unittest

from leadbot.discovery.sources import load_regions_map
from leadbot.ui.ui_templates import (
    country_options_html,
    niche_options_html,
    page_html,
    region_options_html,
)


class UiTemplatesTests(unittest.TestCase):
    def test_page_renders_core_sections(self):
        page = page_html()
        self.assertIn('id="run-button"', page)
        self.assertIn('id="status-badge"', page)
        self.assertIn('id="progress-bar"', page)
        self.assertIn('id="log"', page)
        self.assertIn('id="run-form"', page)
        self.assertIn("Run lead collection", page)
        self.assertIn('<option value="United States" selected>', page)
        self.assertIn('<option value="Texas" selected>', page)
        self.assertIn('id="region-value" value="Texas"', page)
        self.assertIn("var REGIONS=", page)
        self.assertNotIn("Could not start", page)

    def test_page_prefills_last_query_and_selects_niche(self):
        page = page_html(last_query={"country": "Canada", "region": "Ontario", "niche": "clinic"})
        self.assertIn('<option value="Canada" selected>', page)
        self.assertIn('<option value="Ontario" selected>', page)
        self.assertIn('id="region-value" value="Ontario"', page)
        self.assertIn('<option value="clinic" selected>', page)

    def test_unknown_region_falls_back_to_manual_entry(self):
        page = page_html(last_query={"country": "United States", "region": "Atlantis", "niche": "cafe"})
        self.assertIn('<option value="__custom__" selected>', page)
        self.assertIn('id="region-custom"', page)
        self.assertIn('id="region-value" value="Atlantis"', page)

    def test_unknown_country_is_kept_and_appended(self):
        page = page_html(last_query={"country": "Atlantis Island", "region": "Poseidon Bay", "niche": "cafe"})
        self.assertIn('<option value="Atlantis Island" selected>', page)
        self.assertIn('<option value="__custom__" selected>', page)
        self.assertIn('id="region-value" value="Poseidon Bay"', page)

    def test_page_escapes_user_input(self):
        payload = 'Tex"><script>alert(1)</script>'
        page = page_html(last_query={"country": payload, "region": "x", "niche": "clinic"})
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("&lt;script&gt;alert(1)", page)

    def test_error_banner_renders_and_escapes(self):
        page = page_html(error_message="boom <b>")
        self.assertIn("Could not start:", page)
        self.assertIn("boom &lt;b&gt;", page)
        self.assertNotIn("boom <b>", page)

    def test_niche_options_are_sorted_and_mark_selected(self):
        options = niche_options_html(selected="cafe")
        self.assertIn('<option value="cafe" selected>cafe</option>', options)
        self.assertNotIn('value="clinic" selected', options)
        self.assertLess(options.index('value="accounting_firm"'), options.index('value="veterinary"'))

    def test_region_options_include_manual_fallback(self):
        options = region_options_html("United States")
        self.assertIn('<option value="Austin">', options)
        self.assertIn("Other (type manually)", options)
        self.assertNotIn(" selected", options)

    def test_region_options_mark_manual_fallback_for_unknown_region(self):
        options = region_options_html("United States", "Atlantis")
        self.assertIn('<option value="__custom__" selected>', options)
        self.assertNotIn('value="Austin" selected', options)

    def test_regions_map_shape(self):
        regions = load_regions_map()
        self.assertIn("United States", regions)
        self.assertTrue(all(isinstance(value, list) for value in regions.values()))
        self.assertTrue(all(isinstance(r, str) for value in regions.values() for r in value))


if __name__ == "__main__":
    unittest.main()
