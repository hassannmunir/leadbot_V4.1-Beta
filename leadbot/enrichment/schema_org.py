"""Schema.org JSON-LD contact extraction.

Structured JSON-LD data is the most reliable contact source on a page,
so it is parsed before any regex-based extraction.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

# Schema.org types that indicate a local business
_BUSINESS_SCHEMA_TYPES = {
    "localbusiness", "restaurant", "foodestablishment", "medicalclinic",
    "physician", "dentist", "hospital", "healthandbeautybusiness",
    "professionalservice", "legalservice", "hotel", "lodgingbusiness",
    "automotivebusiness", "store", "organization", "corporation",
    "realestateoragent", "fitnesscenter", "beautysalon", "hairsalon",
    "autodealer", "autorepair", "bakery", "barorcafe", "cafe",
    "accountingservice", "insuranceagency", "movingcompany",
}


def parse_schema_org(html_text: str) -> dict:
    """
    Extract contact info from Schema.org JSON-LD blocks.
    This is the most reliable extraction method - explicitly structured data.
    Returns dict with any of: email, phone, website, social_links
    """
    result = {}
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            # Handle @graph array or single object
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "@graph" in data:
                    items = data["@graph"]
                else:
                    items = [data]

            for item in items:
                if not isinstance(item, dict):
                    continue
                schema_type = item.get("@type", "")
                if isinstance(schema_type, list):
                    schema_type = " ".join(schema_type)
                if not any(t in schema_type.lower() for t in _BUSINESS_SCHEMA_TYPES):
                    continue

                # Phone - telephone field
                if not result.get("phone"):
                    phone = item.get("telephone", "")
                    if phone:
                        result["phone"] = str(phone).strip()

                # Email
                if not result.get("email"):
                    email = item.get("email", "")
                    if email and "@" in str(email):
                        result["email"] = str(email).strip().lower()

                # Website URL
                if not result.get("website"):
                    url = item.get("url", "")
                    if url:
                        result["website"] = str(url).strip()

                # sameAs - social media profiles
                same_as = item.get("sameAs", [])
                if isinstance(same_as, str):
                    same_as = [same_as]
                social_urls = []
                for url in same_as:
                    url_lower = url.lower()
                    if any(s in url_lower for s in (
                        "facebook.com", "instagram.com", "twitter.com",
                        "linkedin.com", "youtube.com", "tiktok.com", "x.com",
                    )):
                        social_urls.append(url)
                if social_urls and not result.get("social_links"):
                    result["social_links"] = " | ".join(social_urls)

                # contactPoint
                contact_point = item.get("contactPoint", {})
                if isinstance(contact_point, list):
                    contact_point = contact_point[0] if contact_point else {}
                if isinstance(contact_point, dict):
                    if not result.get("phone") and contact_point.get("telephone"):
                        result["phone"] = str(contact_point["telephone"]).strip()
                    if not result.get("email") and contact_point.get("email"):
                        result["email"] = str(contact_point["email"]).strip().lower()

    except Exception:
        pass  # Never crash the pipeline on schema parsing

    return result
