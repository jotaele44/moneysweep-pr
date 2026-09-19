import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / ".federation/gui-capabilities.extensions/case-manager-authorization-boundary.json"


def test_case_manager_authorization_is_internal_security_boundary() -> None:
    capability = json.loads(EXTENSION.read_text(encoding="utf-8"))["capabilities"][0]

    assert capability["classification"] == "internal"
    assert capability["requires_terminal"] is False
    assert capability["tests"]["backend"] == ["tests/test_case_manager_auth.py"]
    assert capability["candidate_ids"] == [
        "python_module:server/backend/case_manager_auth.py",
        "python_symbol:server/backend/case_manager_auth.py:CasePrincipal",
        "python_symbol:server/backend/case_manager_auth.py:install_case_auth",
    ]
