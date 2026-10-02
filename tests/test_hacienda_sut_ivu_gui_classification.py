import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".federation/gui-capabilities.extensions/hacienda-sut-ivu-producer.json"


def test_hacienda_sut_ivu_producer_is_fully_classified_as_internal() -> None:
    capability = json.loads(EXTENSION.read_text(encoding="utf-8"))["capabilities"][0]

    assert capability["classification"] == "internal"
    assert capability["requires_terminal"] is False
    assert capability["rationale"].strip()
    assert capability["analysis"]["files"] == ["scripts/download_hacienda_sut_ivu.py"]
    assert len(capability["candidate_ids"]) == 5
    assert len(set(capability["candidate_ids"])) == 5
