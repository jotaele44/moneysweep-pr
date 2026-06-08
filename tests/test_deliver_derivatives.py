import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from deliver_derivatives import deliver  # noqa: E402


class _FakeCopy:
    def __init__(self):
        self.calls = []

    def __call__(self, src, dest):
        self.calls.append((src, dest))
        Path(dest).write_text("delivered")


def test_deliver_copies_into_dropzone(tmp_path):
    derivatives = tmp_path / "exports"
    derivatives.mkdir()
    (derivatives / "spiderweb_pr_derivatives.csv").write_text("record_id\nX\n")
    dropzone = tmp_path / "sibling" / "data" / "intake" / "pr_intake"

    fake = _FakeCopy()
    result = deliver(derivatives, dropzone, copy=fake)

    assert result["filename"] == "spiderweb_pr_derivatives.csv"
    assert result["dest"].endswith("data/intake/pr_intake/spiderweb_pr_derivatives.csv")
    assert dropzone.is_dir()  # created on demand
    assert len(fake.calls) == 1
    assert fake.calls[0][0].endswith("spiderweb_pr_derivatives.csv")


def test_deliver_real_copy_writes_file(tmp_path):
    derivatives = tmp_path / "exports"
    derivatives.mkdir()
    (derivatives / "spiderweb_pr_derivatives.csv").write_text("record_id\nX\n")
    dropzone = tmp_path / "dz"
    deliver(derivatives, dropzone)  # default shutil.copy2
    assert (dropzone / "spiderweb_pr_derivatives.csv").read_text() == "record_id\nX\n"


def test_deliver_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        deliver(tmp_path / "nope", tmp_path / "dz")
