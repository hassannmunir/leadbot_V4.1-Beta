"""Public search contact recovery for leads with no direct contact channels.

This module is deliberately conservative: it only extracts contact information
that is visible in public search-result text/links and requires a strong match
between the lead identity and the result before accepting it.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from ..core.models import Lead
from ..core.utils import extract_emails, extract_social_links, normalize_phone, normalize_url
from ..safety.policy import Guard, retry_request

_PHONE_RE = re.compile(r"(?:\+?\d[\d ()\-.]{7,}\d)")
_EXCLUDED = {
    "duckduckgo.com", "google.com", "bing.com", "yelp.com", "tripadvisor.com",
    "yellowpages.com", "mapquest.com", "foursquare.com", "superpages.com",
    "reddit.com", "pinterest.com", "tiktok.com", "youtube.com", "linkedin.com",
}
_SOCIAL_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "threads.net", "linktr.ee",
}


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(x) > 1}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _identity_score(lead: Lead, text: str) -> float:
    lead_tokens = _tokens(lead.name)
    text_tokens = _tokens(text)
    if not lead_tokens or not text_tokens:
        return 0.0
    overlap = len(lead_tokens & text_tokens) / len(lead_tokens)
    exact = 1.0 if _norm(lead.name) in _norm(text) else 0.0
    location = _tokens(lead.location or lead.region or lead.country)
    loc_score = 0.0 if not location else len(location & text_tokens) / len(location)
    return round(min(1.0, 0.65 * overlap + 0.20 * exact + 0.15 * loc_score), 4)


def _unwrap(href: str) -> str:
    href = html.unescape((href or "").strip())
    p = urlparse(href)
    if p.scheme not in {"http", "https"}:
        return ""
    q = parse_qs(p.query)
    return q.get("uddg", [href])[0]


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _extract_phone(text: str, region: str) -> str:
    for raw in _PHONE_RE.findall(text or ""):
        normalized = normalize_phone(raw, region)
        if len(re.sub(r"\D", "", normalized)) >= 7:
            return normalized
    return ""


def _search(lead: Lead, guard: Guard, search_url: str, max_results: int) -> list[tuple[str, str, str]]:
    location = lead.location or lead.region or lead.country
    queries = [
        f'"{lead.name}" "{location}" phone' if location else f'"{lead.name}" phone',
        f'"{lead.name}" "{location}" email' if location else f'"{lead.name}" email',
        f'"{lead.name}" "{location}" contact' if location else f'"{lead.name}" contact',
    ]
    out, seen = [], set()
    for query in queries:
        if not guard.allowed(search_url):
            break
        host = urlparse(search_url).netloc
        guard.wait(host)
        response = retry_request(
            lambda q=query: requests.get(
                search_url,
                params={"q": q},
                headers={"User-Agent": guard.user_agent, "Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
            ),
            max_attempts=2,
        )
        if response is None or response.status_code != 200:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for result in soup.select(".result"):
            a = result.select_one("a.result__a")
            if not a:
                continue
            url = normalize_url(_unwrap(a.get("href", "")))
            if not url:
                continue
            title = a.get_text(" ", strip=True)
            sn = result.select_one(".result__snippet")
            snippet = sn.get_text(" ", strip=True) if sn else ""
            key = (urlparse(url).netloc.lower(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((url, title, snippet))
            if len(out) >= max_results:
                return out
    return out


def recover_public_contacts(
    lead: Lead,
    guard: Guard,
    min_confidence: float = 0.72,
    max_results: int = 12,
    search_url: str = "https://html.duckduckgo.com/html/",
    phone_region: str = "PK",
) -> bool:
    """Recover a public phone/email/social profile from search results."""
    if lead.phone or lead.email or lead.social_links:
        return False
    results = _search(lead, guard, search_url, max_results)
    changed = False
    for url, title, snippet in results:
        text = f"{title} {snippet}"
        confidence = _identity_score(lead, text)
        if confidence < min_confidence:
            continue

        if not lead.phone:
            phone = _extract_phone(text, phone_region)
            if phone:
                lead.phone = phone
                changed = True

        if not lead.email:
            emails = extract_emails(text)
            if emails:
                lead.email = emails[0]
                changed = True

        host = _host(url)
        if not lead.social_links and host in _SOCIAL_HOSTS:
            lead.social_links = url
            changed = True

        if changed:
            lead.enrichment_stage = f"public_search_contact_verified_{confidence:.2f}"
            lead.notes = f"Public business contact recovered from identity-matched search result ({confidence:.2f}): {url}"
            return True
    return False
