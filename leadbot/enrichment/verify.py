"""
Enhanced website enrichment - orchestration layer.

The heavy lifting lives in focused sibling modules:
  - schema_org.py     : Schema.org JSON-LD parsing (most reliable - structured data)
  - contact_finder.py : contact page auto-detection
  - extractors.py     : phone/email extraction with US format handling
  - wikidata.py       : Wikidata fallback enrichment
  - website_cache.py  : persistent cache for verification results

Extraction priority: Schema.org > mailto/tel links > regex phone/email > social links.
OSM data always preserved - never overwritten.
"""

from __future__ import annotations

import requests
from urllib.parse import urlparse

from ..core.models import Lead
from ..core.utils import extract_social_links, normalize_url
from ..safety.policy import Guard, retry_request
from .contact_finder import find_contact_page_url
from .extractors import extract_email, extract_phone
from .schema_org import parse_schema_org
from .website_cache import WebsiteCache
from .wikidata import enrich_from_wikidata
from .website_discovery import discover_website
from .public_contact_search import recover_public_contacts


# -----------------------------------------------------------------------
# Single page fetch and extraction
# -----------------------------------------------------------------------

def _fetch_page_data(url: str, guard: Guard, phone_region: str) -> dict:
    """
    Fetch one URL and extract all contact data. Returns dict with found fields.
    Extraction is delegated to the sibling modules:
      schema_org.parse_schema_org     -> structured JSON-LD data
      extractors.extract_email        -> mailto links, then visible-text regex
      extractors.extract_phone        -> tel: links, US format, then generic
      core.utils.extract_social_links -> public social profiles
    Priority: Schema.org > mailto links > regex phone/email > social links
    """
    try:
        host = urlparse(url).netloc
        if not guard.allowed(url):
            return {}

        guard.wait(host)
        response = retry_request(
            lambda: requests.get(
                url,
                headers={
                    "User-Agent": guard.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
                allow_redirects=True,
            ),
            max_attempts=3,
        )

        if response is None or response.status_code != 200:
            return {}

        html_text = response.text
        result = {}

        # 1. Schema.org (most reliable)
        schema_data = parse_schema_org(html_text)
        result.update({k: v for k, v in schema_data.items() if v})

        # 2-3. Email: mailto links first, then regex over visible text
        if not result.get("email"):
            email = extract_email(html_text)
            if email:
                result["email"] = email

        # 4. Phone: tel: links, US format, then generic regex
        if not result.get("phone"):
            phone = extract_phone(html_text, phone_region)
            if phone:
                result["phone"] = phone

        # 5. Social links
        if not result.get("social_links"):
            socials = extract_social_links(html_text)
            if socials:
                result["social_links"] = socials

        return result

    except Exception:
        return {}


# -----------------------------------------------------------------------
# Main enrichment entry point
# -----------------------------------------------------------------------

def verify_website(
    lead: Lead,
    guard: Guard,
    phone_region: str = "US",
    website_cache: WebsiteCache | None = None,
    website_discovery_enabled: bool = True,
    website_discovery_min_confidence: float = 0.68,
    website_discovery_max_results: int = 6,
    website_discovery_search_url: str = "https://html.duckduckgo.com/html/",
    public_contact_search_enabled: bool = True,
    public_contact_search_min_confidence: float = 0.72,
    public_contact_search_max_results: int = 12,
) -> Lead:

    # ------------------------------------------------------------------
    # CASE 1: No website in OSM -- use verified enrichment cascade.
    # ------------------------------------------------------------------
    if not lead.website:
        lead.website_status = "no_website_found"
        lead.enrichment_stage = "osm_no_website"

        # First use Wikidata because it is structured and conservative.
        enrich_from_wikidata(lead, guard)
        if lead.website:
            lead.enrichment_stage = "wikidata_website"

        # If Wikidata did not recover a website/contact, use public-search
        # discovery. A candidate is accepted only after identity scoring;
        # the normal website verifier then performs the actual fetch/extraction.
        if website_discovery_enabled and not lead.website and not (lead.phone or lead.email or lead.social_links):
            try:
                discover_website(
                    lead, guard,
                    min_confidence=website_discovery_min_confidence,
                    max_results=website_discovery_max_results,
                    search_url=website_discovery_search_url,
                )
            except Exception as exc:
                lead.notes = f"Website discovery error: {exc}"

        # Even when no official website is discoverable, public search results
        # can expose a verified business phone/email/social profile. This is a
        # separate path so a missing website does not make a lead unreachable.
        if public_contact_search_enabled and not (lead.phone or lead.email or lead.social_links):
            try:
                recover_public_contacts(
                    lead, guard,
                    min_confidence=public_contact_search_min_confidence,
                    max_results=public_contact_search_max_results,
                    search_url=website_discovery_search_url,
                    phone_region=phone_region,
                )
            except Exception as exc:
                lead.notes = f"Public contact search error: {exc}"

        has_something = bool(lead.phone or lead.email or lead.social_links or lead.website)
        if not lead.website:
            lead.enrichment_stage = "contact_enrichment_only" if has_something else "enrichment_exhausted"
            lead.notes = (
                f"No website found. Contact info recovered via enrichment. {lead.notes}"
                if has_something
                else "No website found after OSM, Wikidata, and public-search enrichment."
            )
            return lead
        # A verified/discovered website falls through to normal website checks.

    # ------------------------------------------------------------------
    # CASE 2: We have a website URL -- check cache first
    # ------------------------------------------------------------------
    url = normalize_url(lead.website)

    if not url:
        lead.website_status = "invalid_url"
        lead.notes = "Website URL invalid."
        enrich_from_wikidata(lead, guard)
        return lead

    if website_cache and website_cache.load(lead):
        enrich_from_wikidata(lead, guard)
        website_cache.save(lead)
        return lead

    # ------------------------------------------------------------------
    # Robots.txt check
    # ------------------------------------------------------------------
    if not guard.allowed(url):
        lead.website_status = "robots_denied"
        lead.notes = "Website robots.txt disallows access. Trying Wikidata."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    # ------------------------------------------------------------------
    # Fetch homepage
    # ------------------------------------------------------------------
    host = urlparse(url).netloc
    guard.wait(host)

    try:
        response = retry_request(
            lambda: requests.get(
                url,
                headers={
                    "User-Agent": guard.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
                allow_redirects=True,
            ),
            max_attempts=3,
        )
    except Exception:
        response = None

    if response is None:
        lead.website_status = "unreachable"
        lead.notes = "Website did not respond. Trying Wikidata."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    if response.status_code in (403, 404, 410, 429):
        lead.website_status = str(response.status_code)
        lead.notes = f"Website HTTP {response.status_code} (rebuild prospect). Trying Wikidata."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    if response.status_code != 200:
        lead.website_status = str(response.status_code)
        lead.notes = f"Website HTTP {response.status_code}."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    lead.website_status = "200"
    if not lead.enrichment_stage or lead.enrichment_stage == "osm_no_website":
        lead.enrichment_stage = "website_verified"
    homepage_html = response.text

    # ------------------------------------------------------------------
    # Extract from homepage
    # ------------------------------------------------------------------
    homepage_data = _fetch_page_data(url, guard, phone_region)

    # Fill gaps from homepage (OSM data takes priority - never overwrite)
    if not lead.email and homepage_data.get("email"):
        lead.email = homepage_data["email"]
    if not lead.phone and homepage_data.get("phone"):
        lead.phone = homepage_data["phone"]
    if not lead.social_links and homepage_data.get("social_links"):
        lead.social_links = homepage_data["social_links"]

    # ------------------------------------------------------------------
    # Fetch contact page IF we still have gaps
    # ------------------------------------------------------------------
    still_missing = not lead.email or not lead.phone or not lead.social_links
    if still_missing:
        contact_url = find_contact_page_url(homepage_html, url)
        if contact_url and contact_url.rstrip("/") != url.rstrip("/"):
            contact_data = _fetch_page_data(contact_url, guard, phone_region)
            if not lead.email and contact_data.get("email"):
                lead.email = contact_data["email"]
            if not lead.phone and contact_data.get("phone"):
                lead.phone = contact_data["phone"]
            if not lead.social_links and contact_data.get("social_links"):
                lead.social_links = contact_data["social_links"]

    # ------------------------------------------------------------------
    # Public search fallback for websites that expose no contact details.
    # ------------------------------------------------------------------
    if public_contact_search_enabled and not (lead.phone or lead.email or lead.social_links):
        try:
            recover_public_contacts(
                lead, guard,
                min_confidence=public_contact_search_min_confidence,
                max_results=public_contact_search_max_results,
                search_url=website_discovery_search_url,
                phone_region=phone_region,
            )
        except Exception as exc:
            lead.notes = f"Public contact search error: {exc}"

    # ------------------------------------------------------------------
    # Wikidata as final fallback
    # ------------------------------------------------------------------
    enrich_from_wikidata(lead, guard)

    # ------------------------------------------------------------------
    # Build notes
    # ------------------------------------------------------------------
    sources = ["website"]
    if "website_discovery_verified" in (lead.enrichment_stage or ""):
        sources.append("public search")
    if still_missing and contact_url:
        sources.append("contact page")
    if "[Wikidata:" in (lead.notes or ""):
        sources.append("Wikidata")

    has_contact = bool(lead.email or lead.phone or lead.social_links)
    if has_contact:
        lead.enrichment_stage = "website_verified_contactable"
    else:
        lead.enrichment_stage = "website_verified_no_contact"
    lead.notes = (
        f"Contact info found via: {', '.join(sources)}."
        if has_contact
        else "Website reachable but no contact details found on page, contact page, or Wikidata."
    )

    if website_cache:
        website_cache.save(lead)

    return lead