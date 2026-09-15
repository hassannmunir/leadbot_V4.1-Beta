"""Shared helpers: URL/phone normalization, email/social extraction, scoring."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d ()-]{7,}\d)")
SOCIAL_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "threads.net", "reddit.com", "pinterest.com",
    "snapchat.com", "telegram.me", "t.me", "discord.com", "discord.gg",
    "twitch.tv", "vimeo.com", "medium.com", "github.com", "mastodon.social",
    "bsky.app", "linktr.ee",
}
SOCIAL_PATH_BLOCKLIST = ("/share", "/sharer", "/intent", "/login", "/signup", "/oauth")

# Post/media URL patterns — these are content pages not business profiles
# Instagram: /p/ (post), /reel/, /tv/, /reels/
# Facebook:  /permalink/, /photos/, /posts/, /events/, /videos/
_SOCIAL_POST_PATH_RE = re.compile(
    r"^/(p|reel|tv|reels|permalink|photos|posts|events|videos|watch|stories)/",
    re.I,
)

# Placeholder/template emails that websites use as examples — never real
_FAKE_EMAIL_RE = re.compile(
    r"(user@domain|name@domain|email@domain|your@email|info@example"
    r"|name@company|user@example|test@test|admin@example|hello@example"
    r"|contact@example|mail@example|example\.com$|yourdomain\.com$"
    r"|yoursite\.com$|placeholder|noreply@|no-reply@|donotreply@"
    r"|webmaster@|postmaster@|mailer-daemon@)",
    re.I,
)

# Instagram paths that are NOT posts but ARE deep (explore, tags, etc.)
_INSTAGRAM_NON_POST_DEEP = re.compile(
    r"^/(explore|tags|accounts|directory|developer|about|legal|help)/",
    re.I,
)

AI_FIT_PROFILES = {
    "clinic": (90, "appointment booking, patient intake, reminders and medical FAQs"),
    "hospital": (90, "department routing, appointment requests, patient FAQs and reminders"),
    "dentist": (88, "appointment booking, treatment FAQs, reminders and intake"),
    "doctor": (85, "appointment requests, patient FAQs, reminders and intake"),
    "real_estate": (88, "property qualification, viewing bookings and lead follow-up"),
    "hotel": (85, "availability questions, booking support and concierge FAQs"),
    "university": (85, "admissions FAQs, applicant qualification and campus scheduling"),
    "school": (80, "admissions enquiries, parent FAQs and tour scheduling"),
    "law_firm": (82, "client intake, consultation booking and practice-area FAQs"),
    "restaurant": (78, "reservation requests, menu questions, order support and delivery updates"),
    "cafe": (70, "reservation questions, menu information and order support"),
    "auto_repair": (78, "service booking, repair quotes and vehicle-status updates"),
    "gym": (76, "trial booking, membership questions and renewal reminders"),
    "salon": (76, "appointment booking, service selection and reminders"),
    "spa": (76, "appointment booking, treatment questions and reminders"),
    "veterinary": (78, "appointment booking, pet-care FAQs and vaccination reminders"),
    "pharmacy": (62, "hours and stock questions, refill requests and pickup updates"),
    "guest_house": (72, "availability questions, booking support and guest FAQs"),
    "fast_food": (65, "menu questions, order support and pickup-status updates"),
    "bakery": (55, "custom-order enquiries, availability questions and pickup scheduling"),
    "bar": (52, "reservation enquiries, event questions and opening-hours support"),
    "accounting_firm": (70, "consultation booking, document-intake guidance and deadline FAQs"),
    "insurance_agency": (68, "quote qualification, appointment booking and policy FAQs"),
    "marketing_agency": (65, "lead qualification, discovery-call booking and service FAQs"),
    "it_company": (78, "demo qualification, support triage and onboarding guidance"),
    "plumber": (65, "service-area qualification, emergency intake and quote requests"),
    "electrician": (65, "service qualification, appointment booking and quote requests"),
    "car_dealer": (62, "vehicle enquiries, test-drive bookings and lead follow-up"),
    "bank": (58, "service FAQs, appointment routing and application guidance"),
    "supermarket": (45, "store-hours, product-availability and pickup FAQs"),
    "grocery": (45, "product-availability, store-hours and pickup questions"),
    "electronics_store": (48, "product questions, availability checks and support routing"),
    "furniture_store": (48, "product enquiries, delivery questions and showroom bookings"),
    "jewelry_store": (48, "product enquiries, appointment booking and order-status questions"),
    "clothing_store": (42, "product availability, sizing questions and order support"),
    "bookstore": (40, "availability questions, event enquiries and order support"),
    "tailor": (55, "fitting bookings, quote requests and order-status updates"),
    "dry_cleaning": (50, "service pricing, pickup scheduling and order-status updates"),
    "photographer": (58, "package enquiries, availability checks and booking requests"),
}


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if "." in value:
        return "https://" + value
    return value


def normalize_phone(value, region: str = "PK") -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    raw = re.sub(r"[^\d+]", "", text)
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("+"):
        return raw
    if region.upper() == "PK" and raw.startswith("0") and len(raw) >= 10:
        return "+92" + raw[1:]
    if region.upper() == "US" and len(raw) == 10:
        return "+1" + raw
    return raw


def extract_emails(raw_html: str) -> list[str]:
    text = html.unescape(raw_html or "")
    found = EMAIL_RE.findall(text.replace("[at]", "@").replace("(at)", "@"))
    found += [m.split("?", 1)[0] for m in re.findall(r"mailto:([^\"' >]+)", text, re.I)]
    cleaned = []
    seen = set()
    for e in found:
        e = e.strip(" .,;:()[]<>").lower()
        if not e or "@" not in e:
            continue
        if e in seen:
            continue
        # Reject placeholder/fake emails
        if _FAKE_EMAIL_RE.search(e):
            continue
        seen.add(e)
        cleaned.append(e)

    # Prefer business domain emails over generic providers
    business = [
        e for e in cleaned
        if not re.search(r"@(gmail|yahoo|hotmail|outlook|icloud|aol)\.", e)
    ]
    return business if business else cleaned


def extract_social_links(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        href = normalize_url(html.unescape(a["href"].strip()))
        if not href or href in seen:
            continue
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        host = parsed.hostname.lower().removeprefix("www.")
        path = parsed.path.lower().rstrip("/")

        is_known_social = any(
            host == domain or host.endswith(f".{domain}")
            for domain in SOCIAL_HOSTS
        )
        is_explicit_profile = "me" in {value.lower() for value in a.get("rel", [])}
        if not is_known_social and not is_explicit_profile:
            continue

        # Reject post/reel/photo content URLs
        if _SOCIAL_POST_PATH_RE.match(parsed.path):
            continue

        # Reject generic path blocklist (share, login, etc.)
        path_segments = set(filter(None, path.split("/")))
        if (
            any(path == blocked or path.startswith(f"{blocked}/") for blocked in SOCIAL_PATH_BLOCKLIST)
            or any(blocked.strip("/") in path_segments for blocked in SOCIAL_PATH_BLOCKLIST)
        ):
            continue

        # For Instagram/Facebook: reject deep paths that are clearly not profiles
        # BUT allow known non-post deep paths like /explore/locations/
        path_parts = [p for p in parsed.path.split("/") if p]
        if host in ("instagram.com", "facebook.com") and len(path_parts) >= 3:
            # Allow explore/locations (location pages are valid business references)
            # Allow facebook /pages/name/id structure
            first = path_parts[0].lower()
            if first == "pages" and host == "facebook.com":
                pass  # Facebook pages — keep
            elif first == "explore" and host == "instagram.com":
                pass  # Instagram explore/locations — keep
            else:
                continue  # Deep path, unknown type — reject

        seen.add(href)
        links.append(href)
    return " | ".join(links)


def quality_score(lead) -> int:
    score = 0
    if lead.name:
        score += 15
    if lead.niche:
        score += 15
    if lead.website:
        score += 20
    if lead.email and not any(x in lead.email.lower() for x in ("gmail.", "yahoo.", "hotmail.", "outlook.")):
        score += 25
    if lead.phone:
        score += 15
    if lead.location:
        score += 10
    return score


def assess_ai_agent_fit(lead):
    profile = AI_FIT_PROFILES.get((lead.niche or "").strip().lower())
    if not profile:
        lead.ai_agent_fit_score = 0
        lead.ai_agent_priority = "low"
        lead.ai_agent_opportunities = ""
        return lead

    base_score, opportunities = profile
    website_status = (lead.website_status or "").strip().lower()
    inactive_statuses = {"403", "404", "410", "429", "unreachable", "robots_denied"}
    has_website = bool((lead.website or "").strip()) and website_status not in inactive_statuses
    has_phone = bool((lead.phone or "").strip())
    has_email = bool((lead.email or "").strip())
    has_social = bool((lead.social_links or "").strip())
    has_full_contact = has_phone and (has_email or has_social)

    if has_website and has_full_contact:
        score = min(95, max(85, base_score + 5))
        priority = "high"
    elif has_website:
        score = min(84, max(70, base_score))
        priority = "high"
    else:
        contact_evidence = sum((has_phone, has_email, has_social))
        score = min(30, 10 + contact_evidence * 6)
        priority = "low"

    lead.ai_agent_fit_score = score
    lead.ai_agent_priority = priority
    lead.ai_agent_opportunities = opportunities
    return lead