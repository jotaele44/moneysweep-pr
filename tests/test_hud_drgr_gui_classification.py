import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".federation/gui-capabilities.extensions/hud-drgr-authorized-pursuit.json"


def test_hud_drgr_pursuit_is_fully_classified_as_internal() -> None:
    capability = json.loads(EXTENSION.read_text(encoding="utf-8"))["capabilities"][0]

    assert capability["classification"] == "internal"
    assert capability["requires_terminal"] is False
    assert capability["tests"]["backend"] == ["tests/test_audit_hud_drgr_authorized_sources.py"]
    assert len(capability["candidate_ids"]) == 9
    assert len(set(capability["candidate_ids"])) == 9
