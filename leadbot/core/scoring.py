"""V4 lead scoring: contactability, lead quality, and sales priority are separate.

The old scorer mixed contact availability and business quality into one score.
V4 keeps the three decisions independent so enrichment can improve reachability
without artificially inflating sales priority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import pandas as pd

ACTIVE_WEBSITE_STATUSES = {"200", "202"}
BROKEN_WEBSITE_STATUSES = {"403", "404", "410", "429", "503", "unreachable", "robots_denied"}
HEALTHCARE_PATTERN = re.compile(r"clinic|health|medical|doctor|dental|hospital|veterinary", re.IGNORECASE)
REAL_ESTATE_PATTERN = re.compile(r"real[_ -]?estate|realtor|property|broker", re.IGNORECASE)
HOSPITALITY_PATTERN = re.compile(r"restaurant|food|bar|cafe|bakery|pizza|hotel", re.IGNORECASE)


class LeadScorer:
    """Compute independent V4 scores and preserve the legacy score fields."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        cw = config.get("contactability_weights", {})
        sw = config.get("sales_priority_weights", {})
        self.contact_weights = {
            "phone": int(cw.get("phone", 40)),
            "email": int(cw.get("email", 40)),
            "social": int(cw.get("social", 20)),
        }
        self.sales_weights = {
            "lead_quality": float(sw.get("lead_quality", 0.50)),
            "contactability": float(sw.get("contactability", 0.30)),
            "ai_fit": float(sw.get("ai_fit", 0.20)),
        }
        total = sum(self.sales_weights.values())
        if total <= 0:
            raise ValueError("V4 sales_priority_weights must sum to a positive value")
        if abs(total - 1.0) > 0.001:
            self.sales_weights = {key: value / total for key, value in self.sales_weights.items()}

    def _text(self, value) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    def _valid_phone(self, value) -> bool:
        return len(re.sub(r"\D", "", self._text(value))) >= 7

    def _valid_email(self, value) -> bool:
        text = self._text(value).lower()
        if "@" not in text:
            return False
        local, domain = text.rsplit("@", 1)
        return bool(local) and "." in domain and not domain.endswith(".")

    def _channels(self, lead: Mapping) -> tuple[bool, bool, bool]:
        return (
            self._valid_phone(lead.get("phone")),
            self._valid_email(lead.get("email")),
            bool(self._text(lead.get("social_links"))),
        )

    def _contactability(self, lead: Mapping) -> tuple[int, str, bool, int]:
        phone, email, social = self._channels(lead)
        # Direct channels carry more weight than social-only discovery.
        score = (self.contact_weights["phone"] if phone else 0) + (self.contact_weights["email"] if email else 0) + (self.contact_weights["social"] if social else 0)
        count = int(phone) + int(email) + int(social)
        if phone and email:
            tier = "A - Multi-channel"
        elif phone or email:
            tier = "B - Direct contact"
        elif social:
            tier = "C - Social contact"
        else:
            tier = "D - Uncontactable"
        return score, tier, count > 0, count

    def _website_quality(self, status: str, website: str) -> int:
        status = self._text(status).lower()
        if status in ACTIVE_WEBSITE_STATUSES:
            return 20
        if status in BROKEN_WEBSITE_STATUSES:
            return 10
        if self._text(website):
            return 12
        return 4

    def _niche_fit(self, niche) -> int:
        text = self._text(niche)
        if HEALTHCARE_PATTERN.search(text):
            return 25
        if REAL_ESTATE_PATTERN.search(text):
            return 24
        if HOSPITALITY_PATTERN.search(text):
            return 22
        return 14 if text else 6

    def _data_confidence(self, lead: Mapping) -> int:
        score = 0
        if self._text(lead.get("name")):
            score += 6
        if len(self._text(lead.get("location"))) > 4:
            score += 5
        if self._text(lead.get("source_url")):
            score += 4
        # Verified website discovery gets a small confidence bonus without
        # turning discovery itself into contactability.
        stage = self._text(lead.get("enrichment_stage")).lower()
        if "verified" in stage or "website" in stage:
            score += 5
        return min(20, score)

    def _lead_quality(self, lead: Mapping) -> int:
        score = (
            self._niche_fit(lead.get("niche"))
            + self._website_quality(lead.get("website_status"), lead.get("website"))
            + self._data_confidence(lead)
            + (10 if len(self._text(lead.get("location"))) > 4 else 0)
            + (5 if self._text(lead.get("source_url")) else 0)
        )
        return max(0, min(100, score))

    def _ai_fit(self, niche) -> int:
        text = self._text(niche).lower()
        if HEALTHCARE_PATTERN.search(text):
            return 95
        if REAL_ESTATE_PATTERN.search(text):
            return 92
        if HOSPITALITY_PATTERN.search(text):
            return 88
        if text:
            return 72
        return 40

    def _sales_priority(self, lead_quality: int, contactability: int, ai_fit: int) -> tuple[int, str]:
        # Quality is deliberately dominant; contactability determines whether
        # a good prospect can be worked now, rather than whether it is good.
        score = round(
            self.sales_weights["lead_quality"] * lead_quality
            + self.sales_weights["contactability"] * contactability
            + self.sales_weights["ai_fit"] * ai_fit
        )
        if score >= 80:
            priority = "Hot"
        elif score >= 65:
            priority = "High"
        elif score >= 50:
            priority = "Medium"
        else:
            priority = "Nurture / Enrich"
        return score, priority

    def _offer(self, contactable: bool, website_status: str) -> str:
        status = self._text(website_status).lower()
        if not contactable:
            return "Enrichment Required"
        if status in ACTIVE_WEBSITE_STATUSES:
            return "AI Agent Integration"
        if status in BROKEN_WEBSITE_STATUSES:
            return "Website Rebuild + AI Agent"
        return "Full Web Build"

    def score_lead(self, lead: dict) -> dict:
        result = dict(lead)
        contactability, contact_tier, is_contactable, contact_count = self._contactability(result)
        lead_quality = self._lead_quality(result)
        ai_fit = self._ai_fit(result.get("niche"))
        sales_score, sales_priority = self._sales_priority(lead_quality, contactability, ai_fit)

        result["contactability_score"] = contactability
        result["contactability_tier"] = contact_tier
        result["is_contactable"] = is_contactable
        result["contact_channel_count"] = contact_count
        result["lead_quality_score"] = lead_quality
        result["lead_quality_tier"] = (
            "A - Excellent" if lead_quality >= 80 else
            "B - Strong" if lead_quality >= 65 else
            "C - Usable" if lead_quality >= 50 else
            "D - Weak"
        )
        result["sales_priority_score"] = sales_score
        result["sales_priority"] = sales_priority
        result["ai_agent_fit_score"] = sales_score  # backward-compatible dashboard field
        result["ai_agent_priority"] = sales_priority
        result["recommended_offer"] = self._offer(is_contactable, result.get("website_status"))
        return result

    def score_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Vectorized-compatible batch scorer using the same logic as score_lead."""
        rows = [self.score_lead(row) for row in df.to_dict(orient="records")]
        return pd.DataFrame(rows, index=df.index)
