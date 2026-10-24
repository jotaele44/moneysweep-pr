import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = (
    ROOT / ".federation" / "gui-capabilities.extensions" / "v4-domain-conformance-audit.json"
)


def test_v4_domain_conformance_audit_is_fully_classified_as_internal() -> None:
    capability = json.loads(EXTENSION.read_text(encoding="utf-8"))["capabilities"][0]

    assert capability["classification"] == "internal"
    assert capability["requires_terminal"] is False
    assert capability["rationale"].strip()
    assert capability["analysis"]["files"] == ["scripts/audit_v4_domain_conformance.py"]
    assert capability["candidate_ids"] == [
        "analysis_module:scripts/audit_v4_domain_conformance.py",
        "analysis_symbol:scripts/audit_v4_domain_conformance.py:audit",
        "analysis_symbol:scripts/audit_v4_domain_conformance.py:main",
    ]
