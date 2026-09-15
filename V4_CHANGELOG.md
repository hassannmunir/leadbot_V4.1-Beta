# LeadBot V4 — Contactability / Quality / Sales Priority

## Objective
Raise the real contactable-lead rate toward 70% without inflating the rate by changing labels. V3 had 509 contactable leads out of 935 (54.44%), so the operating target is 655+ contactable leads for a 70% rate.

## V4 scoring

### Contactability Score (0–100)
- Phone: 40
- Email: 40
- Social profile: 20
- Contactable = phone OR email OR social

Tiers:
- A — Multi-channel: phone + email
- B — Direct contact: phone or email
- C — Social contact: social only
- D — Uncontactable: no usable contact channel

### Lead Quality Score (0–100)
Independent of contact availability. Uses:
- niche/business fit
- website health/presence
- identity/data confidence
- location/source evidence

A lead can therefore be high quality while still being uncontactable and needing enrichment.

### Sales Priority Score (0–100)
- 50% Lead Quality
- 30% Contactability
- 20% AI-agent fit

Bands:
- Hot: 80+
- High: 65–79
- Medium: 50–64
- Nurture / Enrich: below 50

The legacy `ai_agent_fit_score` / `ai_agent_priority` fields are populated from the V4 sales score for compatibility with existing sheets/UI.

## V4 enrichment cascade

For OSM leads with no website and no contact channel:

1. OSM contact tags remain authoritative.
2. Wikidata is tried first for structured, verified properties.
3. Public-search website discovery runs when no website/contact was recovered.
4. Up to two conservative business-name/location searches are used.
5. Candidate domains are filtered to avoid search engines, social networks, and major directory sites.
6. Candidate identity is scored from result title/snippet and then validated again from the candidate homepage.
7. Only a sufficiently strong identity match is accepted.
8. The accepted website goes through the existing robots-aware website/contact-page/schema extraction pipeline.

No CAPTCHA bypass, login bypass, proxy rotation, or robots bypass is used.

## Configuration

`config.json` enables website discovery by default:
- `website_discovery_enabled`: true
- `website_discovery_min_confidence`: 0.68
- `website_discovery_max_results`: 6
- `website_discovery_search_url`: configurable public search endpoint
- `v4_scoring.target_contactability_percent`: 70

The 70% target is a benchmark. The code does not mark a lead contactable unless a real phone, email, or social contact channel exists.

## Validation

The full test suite passes: **44 tests, 0 failures**.

## V4.1 — High-recall enrichment pass

This optimization focuses on moving real leads from **uncontactable** to **contactable** without weakening the contactability definition or accepting low-confidence business matches.

### Added
- Public-search contact recovery for leads with no phone, email, or social contact.
- Identity-gated extraction of phone/email/social data from public search results.
- Additional same-domain contact endpoint probing (`/contact`, `/contact-us`, `/about`, `/about-us`, `/get-in-touch`) when a reachable website exposes no contact details.
- More website discovery candidates and a slightly wider discovery threshold while retaining page-level identity validation.
- Configurable V4.1 enrichment controls in `config.json`.

### Safety principle
V4.1 increases recall through additional public sources and paths; it does **not** redefine a lead as contactable just because it has a website, business name, or low-confidence search result.

### Validation
- Test suite: **56 passed**.
- Live search-provider success still depends on network availability, provider response, robots rules, and the target business's public footprint. A 60–65% rate is a target, not a guarantee.
