"""Plain-HTML contact extraction: mailto/tel links, regex email and phone.

These run after the structured-data parser (schema_org) has had first pick,
so they only ever fill the gaps the page's markup left behind.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..core.utils import PHONE_RE, extract_emails, normalize_phone

# US phone regex - more specific than the generic one
_US_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(\+?1[\s.\-]?)?"
    r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"(?!\d)"
)

# Fragments that mark an address as generic/placeholder rather than a
# real business inbox.
_PLACEHOLDER_EMAIL_FRAGMENTS = (
    "noreply", "no-reply", "donotreply", "example.com",
    "yourname", "info@example", "email@domain",
)


def extract_email(html_text: str) -> str:
    """
    Extract the best business email from one page of HTML.
    Priority: mailto links (explicit intent) > regex over visible text.
    Returns "" when nothing usable is found.
    """
    # Mailto links (very reliable - explicit intent)
    mailto_emails = re.findall(r"mailto:([^\s\"'>?&]+)", html_text, re.I)
    if mailto_emails:
        email = mailto_emails[0].split("?")[0].strip().lower()
        if "@" in email and "." in email.split("@")[-1]:
            return email

    # Regex email from visible text, filtered for placeholders
    emails = extract_emails(html_text)
    business_emails = [
        e for e in emails
        if not any(x in e for x in _PLACEHOLDER_EMAIL_FRAGMENTS)
    ]
    return business_emails[0] if business_emails else ""


def extract_phone(html_text: str, phone_region: str = "US") -> str:
    """
    Extract the best phone number from one page of HTML.
    Priority: tel: links > US-format regex (US region only) > generic regex.
    Returns a normalized number, or "" when nothing valid is found.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Tel: links first (most reliable)
    tel_links = re.findall(r"tel:([+\d\s\-\(\)]+)", html_text, re.I)
    if tel_links:
        normalized = normalize_phone(tel_links[0].strip(), phone_region)
        if normalized:
            return normalized

    # Fallback: US phone regex on text (only meaningful for the US region)
    if phone_region.upper() == "US":
        us_phones = _US_PHONE_RE.findall(text)
        if us_phones:
            # Take first valid one
            for raw in us_phones[:5]:
                if isinstance(raw, tuple):
                    raw = "".join(raw)
                normalized = normalize_phone(raw, phone_region)
                if normalized and len(re.sub(r"\D", "", normalized)) >= 10:
                    return normalized

    # Generic fallback
    phones = list(dict.fromkeys(PHONE_RE.findall(text)))
    if phones:
        normalized = normalize_phone(phones[0], phone_region)
        if normalized:
            return normalized

    return ""
