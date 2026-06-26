"""Unit tests for the pure/fast runtime helpers (Wave G, PR 5).

Covers four previously-untested stdlib-only modules:
  - moneysweep.runtime.evidence_tiers
  - moneysweep.runtime.file_hash_runtime
  - moneysweep.runtime.retry_runtime
  - moneysweep.runtime.pagination_runtime

(risk_signal_gates is already exercised by tests/test_risk_signals.py.)
"""

from __future__ import annotations

import hashlib

import pytest

from moneysweep.runtime import (
    evidence_tiers as et,
    file_hash_runtime as fh,
    pagination_runtime as pg,
    retry_runtime as rr,
)

# --------------------------------------------------------------------------- #
# evidence_tiers
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "source_type,expected",
    [
        ("registry", "T1"),
        ("filing", "T1"),
        ("court_docket", "T1"),
        ("csv", "T2"),
        ("api", "T2"),
        ("pdf", "T2"),
        ("web", "T3"),
        ("other", "T4"),
        ("totally-unknown", "T4"),
        ("", "T4"),
    ],
)
def test_derive_tier_by_source_type(source_type, expected):
    assert et.derive_tier(source_type) == expected


@pytest.mark.unit
def test_derive_tier_is_case_and_whitespace_insensitive_on_source():
    assert et.derive_tier("  REGISTRY  ") == "T1"


@pytest.mark.unit
def test_derive_tier_method_cap_lowers_but_never_raises_trust():
    # OCR caps a T1 source down to T3 (worst-tier wins).
    assert et.derive_tier("registry", "OCR") == "T3"
    # A high-trust method cannot lift a low-trust source: web stays T3.
    assert et.derive_tier("web", "manual") == "T3"
    # Matching tiers are a no-op.
    assert et.derive_tier("csv", "API") == "T2"
    # Unknown method (not in the cap table) leaves the base untouched.
    assert et.derive_tier("registry", "mystery-method") == "T1"


@pytest.mark.unit
def test_tier_confidence_floors_and_default():
    assert et.tier_confidence("T1") == 0.95
    assert et.tier_confidence("T4") == 0.35
    assert et.tier_confidence("nonsense") == 0.35


@pytest.mark.unit
def test_score_evidence_uses_tier_floor_without_ocr():
    assert et.score_evidence("T1") == 0.95
    assert et.score_evidence("T3") == 0.6


@pytest.mark.unit
def test_score_evidence_ocr_multiplies_by_measured_confidence():
    # T2 floor 0.85 * 0.5 OCR confidence.
    assert et.score_evidence("T2", "OCR", 0.5) == round(0.85 * 0.5, 4)
    # ocr_confidence is clamped into [0, 1].
    assert et.score_evidence("T2", "OCR", 2.0) == 0.85
    assert et.score_evidence("T2", "OCR", -1.0) == 0.0
    # OCR method but no measured confidence -> no penalty.
    assert et.score_evidence("T2", "OCR", None) == 0.85
    # Non-OCR method ignores ocr_confidence entirely.
    assert et.score_evidence("T1", "manual", 0.1) == 0.95


@pytest.mark.unit
def test_claim_tier_for_accepted_mapping():
    assert et.claim_tier_for("T1") == "observed"
    assert et.claim_tier_for("T2") == "observed"
    assert et.claim_tier_for("T3") == "linked"
    assert et.claim_tier_for("T4") == "inferred"


@pytest.mark.unit
def test_claim_tier_for_rejected_is_blocked():
    assert et.claim_tier_for("T1", "rejected") == "blocked"


@pytest.mark.unit
def test_claim_tier_for_unaccepted_downgrades_one_level():
    assert et.claim_tier_for("T1", "pending") == "linked"  # observed -> linked
    assert et.claim_tier_for("T3", "pending") == "inferred"  # linked -> inferred
    assert et.claim_tier_for("T4", "pending") == "blocked"  # inferred -> blocked


# --------------------------------------------------------------------------- #
# file_hash_runtime
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_sha256_file_matches_hashlib(tmp_path):
    data = b"moneysweep-pr public money\n"
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    assert fh.sha256_file(p) == hashlib.sha256(data).hexdigest()


@pytest.mark.unit
def test_sha256_file_empty_file(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert fh.sha256_file(p) == hashlib.sha256(b"").hexdigest()


@pytest.mark.unit
def test_sha256_file_streams_multiple_chunks(tmp_path):
    # Larger than the 1 MiB chunk to exercise the streaming read loop.
    data = b"x" * (fh._CHUNK * 2 + 17)
    p = tmp_path / "big.bin"
    p.write_bytes(data)
    assert fh.sha256_file(p) == hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# retry_runtime
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_with_retry_returns_on_first_success():
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return "value"

    sleeps: list[float] = []
    assert rr.with_retry(ok, sleeper=sleeps.append) == "value"
    assert calls["n"] == 1
    assert sleeps == []  # no backoff on immediate success


@pytest.mark.unit
def test_with_retry_recovers_after_transient_failures():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "recovered"

    sleeps: list[float] = []
    policy = rr.RetryPolicy(max_attempts=5)
    assert rr.with_retry(flaky, policy=policy, sleeper=sleeps.append) == "recovered"
    assert attempts["n"] == 3
    assert len(sleeps) == 2  # slept between the two failures, not after success


@pytest.mark.unit
def test_with_retry_raises_exhausted_and_chains_last_error():
    def always_fail():
        raise RuntimeError("nope")

    sleeps: list[float] = []
    policy = rr.RetryPolicy(max_attempts=3)
    with pytest.raises(rr.RetryExhausted) as ei:
        rr.with_retry(always_fail, policy=policy, sleeper=sleeps.append)
    assert isinstance(ei.value.__cause__, RuntimeError)
    assert len(sleeps) == 2  # max_attempts - 1 backoffs


@pytest.mark.unit
def test_with_retry_does_not_swallow_unlisted_exceptions():
    def boom():
        raise KeyError("programming error")

    sleeps: list[float] = []
    with pytest.raises(KeyError):
        rr.with_retry(boom, retry_on=(ValueError,), sleeper=sleeps.append)
    assert sleeps == []  # never retried


@pytest.mark.unit
def test_compute_delay_is_exponential_and_capped():
    policy = rr.RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=5.0, jitter_fraction=0.0)
    assert rr._compute_delay(1, policy) == 1.0
    assert rr._compute_delay(2, policy) == 2.0
    assert rr._compute_delay(3, policy) == 4.0
    assert rr._compute_delay(4, policy) == 5.0  # capped at max_delay_seconds
    assert rr._compute_delay(10, policy) == 5.0


@pytest.mark.unit
def test_compute_delay_jitter_stays_within_bounds():
    policy = rr.RetryPolicy(base_delay_seconds=2.0, max_delay_seconds=30.0, jitter_fraction=0.25)
    for _ in range(50):
        d = rr._compute_delay(2, policy)  # capped value 4.0, jitter +/- 1.0
        assert 3.0 <= d <= 5.0


# --------------------------------------------------------------------------- #
# pagination_runtime
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_paginate_walks_all_pages_until_none_marker():
    pages = {
        None: pg.PageResult(records=[1, 2], next_marker="p2"),
        "p2": pg.PageResult(records=[3, 4], next_marker="p3"),
        "p3": pg.PageResult(records=[5], next_marker=None),
    }
    seen_markers: list = []

    def fetch(marker):
        seen_markers.append(marker)
        return pages[marker]

    assert list(pg.paginate(fetch)) == [1, 2, 3, 4, 5]
    assert seen_markers == [None, "p2", "p3"]  # started at None, followed markers


@pytest.mark.unit
def test_paginate_honors_start_marker():
    def fetch(marker):
        assert marker == "offset=100"
        return pg.PageResult(records=["a"], next_marker=None)

    assert list(pg.paginate(fetch, start_marker="offset=100")) == ["a"]


@pytest.mark.unit
def test_paginate_max_pages_guards_runaway_loops():
    def fetch(marker):
        # Never terminates on its own — always points to a next page.
        n = 0 if marker is None else marker
        return pg.PageResult(records=[n], next_marker=n + 1)

    # max_pages caps the walk even though next_marker is never None.
    assert list(pg.paginate(fetch, max_pages=3)) == [0, 1, 2]


@pytest.mark.unit
def test_paginate_zero_max_pages_yields_nothing():
    def fetch(marker):  # pragma: no cover - must never be called
        raise AssertionError("fetch should not run when max_pages=0")

    assert list(pg.paginate(fetch, max_pages=0)) == []
