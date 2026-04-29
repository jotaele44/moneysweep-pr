from pathlib import Path

import numpy as np

from scripts.celestial_anomaly_detector import (
    analyze_file,
    collect_media_files,
    robust_z_scores,
    write_outputs,
)


def test_collect_media_files_filters_supported_extensions(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"fake")
    (tmp_path / "b.mp4").write_bytes(b"fake")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")

    files = collect_media_files(tmp_path)
    names = [p.name for p in files]
    assert names == ["a.jpg", "b.mp4"]


def test_collect_media_files_missing_path_returns_empty(tmp_path: Path):
    files = collect_media_files(tmp_path / "not_there")
    assert files == []


def test_robust_z_scores_handles_constant_vector():
    z = robust_z_scores(np.array([10.0, 10.0, 10.0]))
    assert np.allclose(z, np.zeros(3))


def test_analyze_single_image_detects_no_anomalies_on_uniform_image(tmp_path: Path):
    try:
        import cv2
    except ImportError:
        return

    image = np.full((32, 32), 128, dtype=np.uint8)
    img_path = tmp_path / "uniform.png"
    cv2.imwrite(str(img_path), image)

    anomalies = analyze_file(img_path, frame_step=1, anomaly_z_threshold=1.0)
    assert anomalies == []


def test_write_outputs_generates_files(tmp_path: Path):
    out = tmp_path / "out"
    write_outputs([], out)

    assert (out / "anomalies.csv").exists()
    assert (out / "anomalies.json").exists()
