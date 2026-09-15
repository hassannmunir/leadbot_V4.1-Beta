"""Conservative public-search website discovery for leads without a website.

The discovery layer is intentionally separate from website verification. It can
suggest a candidate domain, but only a reasonably strong identity match is
accepted. No CAPTCHA, login, proxy rotation, or robots bypass is performed.
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from ..core.models import Lead, normalize_domain
from ..core.utils import normalize_url
from ..safety.policy import Guard, retry_request

DEFAULT_SEARCH_URL = "https://html.duckduckgo.com/html/"
EXCLUDED_HOSTS = {
    "duckduckgo.com", "google.com", "bing.com", "yelp.com", "tripadvisor.com",
    "yellowpages.com", "mapquest.com", "foursquare.com", "superpages.com",
    "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "reddit.com", "apple.com", "maps.google.com",
}


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(x) > 1}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _name_coverage(a: str, b: str) -> float:
    aa, bb = _tokens(a), _tokens(b)
    if not aa or not bb:
        return 0.0
    if normalize_name(a) == normalize_name(b):
        return 1.0
    return len(aa & bb) / max(1, len(aa))


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _excluded(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in EXCLUDED_HOSTS)


def _unwrap_result_url(href: str) -> str:
    href = html.unescape((href or "").strip())
    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return ""
    params = parse_qs(parsed.query)
    return params["uddg"][0] if params.get("uddg") else href


def _search_once(query: str, guard: Guard, search_url: str, max_results: int) -> list[tuple[str, str, str]]:
    if not guard.allowed(search_url):
        return []
    host = urlparse(search_url).netloc
    guard.wait(host)
    response = retry_request(
        lambda: requests.get(
            search_url,
            params={"q": query},
            headers={"User-Agent": guard.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            timeout=15,
        ),
        max_attempts=2,
    )
    if response is None or response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    for result in soup.select(".result"):
        anchor = result.select_one("a.result__a")
        if not anchor:
            continue
        url = normalize_url(_unwrap_result_url(anchor.get("href", "")))
        if not url or _excluded(url):
            continue
        domain = normalize_domain(url)
        if not domain:
            continue
        title = anchor.get_text(" ", strip=True)
        snippet_el = result.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        candidates.append((url, title, snippet))
        if len(candidates) >= max_results:
            break
    return candidates


def _search_candidates(lead: Lead, guard: Guard, search_url: str, max_results: int) -> list[tuple[str, str, str]]:
    location = lead.location or lead.region or lead.country
    queries = [
        " ".join(x for x in (f'"{lead.name}"', f'"{location}"' if location else "", lead.niche) if x),
        " ".join(x for x in (f'"{lead.name}"', f'"{location}"' if location else "") if x),
    ]
    seen_domains: set[str] = set()
    all_candidates = []
    per_query = max(2, max_results // len(queries))
    for query in queries:
        for item in _search_once(query, guard, search_url, per_query):
            domain = normalize_domain(item[0])
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            all_candidates.append(item)
            if len(all_candidates) >= max_results:
                return all_candidates
    return all_candidates


def _candidate_confidence(lead: Lead, url: str, title: str, snippet: str) -> float:
    text = f"{title} {snippet}"
    name_score = _name_coverage(lead.name, text)
    location_tokens = _tokens(lead.location or lead.region or lead.country)
    location_score = 0.0 if not location_tokens else len(location_tokens & _tokens(text)) / len(location_tokens)
    niche_score = 1.0 if lead.niche and lead.niche.lower() in text.lower() else 0.0
    name_tokens = _tokens(lead.name)
    domain_tokens = _tokens(_host(url).replace(".", " ").replace("-", " "))
    domain_name_score = len(name_tokens & domain_tokens) / max(1, len(name_tokens))
    return round(0.50 * name_score + 0.20 * location_score + 0.10 * niche_score + 0.20 * domain_name_score, 4)


def _page_identity_confidence(lead: Lead, title: str, body: str) -> float:
    text = f"{title} {body[:12000]}"
    name_score = _name_coverage(lead.name, text)
    location_tokens = _tokens(lead.location or lead.region or lead.country)
    location_score = 0.0 if not location_tokens else min(1.0, len(location_tokens & _tokens(text)) / len(location_tokens))
    niche_score = 1.0 if lead.niche and lead.niche.lower() in text.lower() else 0.0
    return round(0.65 * name_score + 0.25 * location_score + 0.10 * niche_score, 4)


def _validate_candidate(lead: Lead, url: str, guard: Guard) -> tuple[bool, dict]:
    """Fetch a candidate homepage and require an identity match before acceptance."""
    if not guard.allowed(url):
        return False, {}
    host = urlparse(url).netloc
    guard.wait(host)
    response = retry_request(
        lambda: requests.get(
            url,
            headers={"User-Agent": guard.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            timeout=15,
            allow_redirects=True,
        ),
        max_attempts=2,
    )
    if response is None or response.status_code != 200:
        return False, {}
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.get_text(" ", strip=True)
    confidence = _page_identity_confidence(lead, title, body)
    return confidence >= 0.62, {"title": title, "confidence": confidence}


def discover_website(
    lead: Lead,
    guard: Guard,
    min_confidence: float = 0.68,
    max_results: int = 6,
    search_url: str = DEFAULT_SEARCH_URL,
) -> bool:
    """Find and accept one likely official website only after two-stage validation."""
    if lead.website:
        return False

    candidates = _search_candidates(lead, guard, search_url, max_results)
    ranked = sorted(
        ((_candidate_confidence(lead, url, title, snippet), url, title, snippet)
         for url, title, snippet in candidates),
        reverse=True,
    )
    for search_confidence, url, title, snippet in ranked:
        if search_confidence < min_confidence:
            continue
        valid, page_data = _validate_candidate(lead, url, guard)
        if not valid:
            continue
        final_confidence = round(0.45 * search_confidence + 0.55 * page_data["confidence"], 4)
        if final_confidence < min_confidence:
            continue
        lead.website = url
        lead.website_status = "discovered_candidate"
        lead.enrichment_stage = f"website_discovery_verified_{final_confidence:.2f}"
        lead.notes = f"Website discovered and identity-validated via public search ({final_confidence:.2f} confidence): {url}"
        return True
    return False
