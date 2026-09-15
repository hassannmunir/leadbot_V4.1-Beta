from leadbot.core.models import Lead
from leadbot.enrichment.public_contact_search import _identity_score, _extract_phone


def test_identity_score_requires_business_name_match():
    lead = Lead(name="Sunrise Dental Clinic", location="Lahore", country="Pakistan")
    assert _identity_score(lead, "Sunrise Dental Clinic Lahore contact") >= 0.8
    assert _identity_score(lead, "Sunset Restaurant Karachi") < 0.72


def test_phone_extraction_normalizes_pk():
    assert _extract_phone("Call +92 300 1234567", "PK") == "+923001234567"
