"""Contact/about page URL detection from homepage HTML."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Contact page URL patterns
_CONTACT_PATH_RE = re.compile(
    r"^/?(contact|contact-us|contactus|reach-us|get-in-touch|about-us|"
    r"about|our-team|connect|location|locations|find-us|visit-us|"
    r"kontakt|nous-contacter|contacto|write-to-us|talk-to-us)[/\-]?(\w*)/?$",
    re.I,
)
_CONTACT_LINK_TEXT = re.compile(
    r"\b(contact|reach|location|find us|write to|talk to|get in touch|connect)\b",
    re.I,
)


def find_contact_page_url(html_text: str, base_url: str) -> str | None:
    """
    Scan homepage HTML for a link to a contact/about page on the same domain.
    Returns the full URL of the best contact page found, or None.
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        base_domain = urlparse(base_url).netloc

        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            link_text = a.get_text(strip=True)

            try:
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
            except Exception:
                continue

            # Must be same domain
            if parsed.netloc != base_domain:
                continue
            # Must be http/https
            if parsed.scheme not in ("http", "https"):
                continue

            path = parsed.path.rstrip("/")
            score = 0

            # Path match
            if _CONTACT_PATH_RE.match(path):
                score += 10
                # Prefer /contact over /about
                if "contact" in path.lower():
                    score += 5

            # Link text match
            if _CONTACT_LINK_TEXT.search(link_text):
                score += 8

            if score > 0:
                candidates.append((score, full_url))

        if not candidates:
            return None

        # Return highest-scored candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    except Exception:
        return None
