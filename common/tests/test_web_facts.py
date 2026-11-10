import pytest
from pydantic import ValidationError

from tkb_common.schemas import ProfileEvidence, WebFact


def fact_data() -> dict[str, str]:
    return {
        "id": "official-1",
        "subject": "青空社",
        "relation": "legal_name_of",
        "object": "株式会社青空",
        "source_url": "https://example.org/company/training",
        "source_title": "架空の公式会社案内",
        "source_kind": "official_organization",
        "excerpt": "青空社の正式名称は株式会社青空です",
        "retrieved_at": "2026-11-10T10:00:00+09:00",
        "verification_status": "verified",
    }


def test_web_fact_and_evidence_keep_source_identity() -> None:
    fact = WebFact.model_validate(fact_data())
    evidence = ProfileEvidence(source="public_web", web_fact_id=fact.id, required=True)
    assert evidence.model_dump(mode="json")["web_fact_id"] == "official-1"
    assert evidence.post_id is None


@pytest.mark.parametrize("url", ["http://example.org/a", "https://user:pass@example.org/a"])
def test_web_fact_rejects_non_public_https(url: str) -> None:
    with pytest.raises(ValidationError):
        WebFact.model_validate({**fact_data(), "source_url": url})


def test_web_evidence_cannot_point_at_post_and_non_web_cannot_point_at_fact() -> None:
    with pytest.raises(ValidationError):
        ProfileEvidence(
            source="public_web", web_fact_id="official-1", post_id="post", required=True
        )
    with pytest.raises(ValidationError):
        ProfileEvidence(post_id="post", clue_index=0, web_fact_id="official-1", required=True)
