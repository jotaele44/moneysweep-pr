"""Exercise the certifier's actual state expression without data-plane imports."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "all_pass, expected",
    [(False, "NON_PRODUCTION_DIAGNOSTIC"), (True, "CERTIFIED")],
)
def test_configuration_cannot_relabel_certification(all_pass: bool, expected: str) -> None:
    path = Path(__file__).resolve().parents[1] / "tools/certify_production.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_report"
    )
    returned = next(node.value for node in function.body if isinstance(node, ast.Return))
    assert isinstance(returned, ast.Dict)
    expression = next(
        value for key, value in zip(returned.keys, returned.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "certification_state"
    )
    code = compile(ast.Expression(expression), str(path), "eval")
    adversarial_config = {
        "states": {"non_production": "CERTIFIED", "certified": "FORGED_LABEL"}
    }
    assert eval(code, {"all_pass": all_pass, "config": adversarial_config}) == expected
