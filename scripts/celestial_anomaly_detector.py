#!/usr/bin/env python3
"""Detect anomalous frames in long-exposure image/video captures.

This tool is aimed at high-volume astrophotography triage. It computes multiple
signal-quality features per frame and ranks frames by anomaly score so analysts
can inspect the most suspicious events first.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}


@dataclass
class FrameAnomaly:
    source_file: str
    frame_index: int
    timestamp_sec: float
    score: float
    motion_score: float
    brightness_z: float
    hot_pixel_ratio: float
    edge_density: float


def collect_media_files(input_path: Path) -> List[Path]:
    """Collect supported media files from a path (single file or directory tree)."""
    if not input_path.exists():
        return []

    if input_path.is_file():
        ext = input_path.suffix.lower()
        return [input_path] if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS else []

    files: List[Path] = []
    for path in sorted(input_path.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
            files.append(path)
    return files


def robust_z_scores(values: np.ndarray) -> np.ndarray:
    """Compute robust z-scores with MAD fallback to std when MAD is zero."""
    if values.size == 0:
        return values

    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        std = np.std(values)
        if std == 0:
            return np.zeros_like(values, dtype=float)
        return (values - np.mean(values)) / std
    return 0.6745 * (values - median) / mad


def _require_cv2() -> None:
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required. Install dependencies from requirements.txt")


def compute_features(gray: np.ndarray, prev_gray: Optional[np.ndarray]) -> Tuple[float, float, float, float]:
    """Extract frame features used for anomaly scoring."""
    _require_cv2()
    mean_brightness = float(np.mean(gray))

    # Gentle denoise to reduce false edges from sensor grain.
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    edge_density = float(np.mean(cv2.Canny(denoised, 20, 60) > 0))

    high = np.percentile(gray, 99.9)
    hot_pixel_ratio = float(np.mean(gray >= high))

    if prev_gray is None:
        motion_score = 0.0
    else:
        diff = cv2.absdiff(gray, prev_gray)
        motion_score = float(np.mean(diff))

    return mean_brightness, edge_density, hot_pixel_ratio, motion_score


def iter_video_frames(path: Path, frame_step: int) -> Iterable[Tuple[int, float, np.ndarray]]:
    """Yield sampled grayscale frames for a video."""
    _require_cv2()
    if frame_step < 1:
        raise ValueError("frame_step must be >= 1")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0

    idx = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            if idx % frame_step != 0:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            yield idx, idx / fps, gray
    finally:
        cap.release()


def iter_image_frame(path: Path) -> Iterable[Tuple[int, float, np.ndarray]]:
    _require_cv2()
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Failed to open image: {path}")
    yield 0, 0.0, img


def analyze_file(path: Path, frame_step: int, anomaly_z_threshold: float) -> List[FrameAnomaly]:
    """Analyze one media file and return ranked anomaly frames."""
    iter_frames = iter_video_frames(path, frame_step) if path.suffix.lower() in VIDEO_EXTENSIONS else iter_image_frame(path)

    frame_rows = []
    prev_gray: Optional[np.ndarray] = None
    for frame_idx, timestamp, gray in iter_frames:
        brightness, edges, hot_pixels, motion = compute_features(gray, prev_gray)
        prev_gray = gray
        frame_rows.append((frame_idx, timestamp, brightness, edges, hot_pixels, motion))

    if not frame_rows:
        return []

    brightness_arr = np.array([r[2] for r in frame_rows], dtype=float)
    edge_arr = np.array([r[3] for r in frame_rows], dtype=float)
    hot_arr = np.array([r[4] for r in frame_rows], dtype=float)
    motion_arr = np.array([r[5] for r in frame_rows], dtype=float)

    z_brightness = robust_z_scores(brightness_arr)
    z_edge = robust_z_scores(edge_arr)
    z_hot = robust_z_scores(hot_arr)
    z_motion = robust_z_scores(motion_arr)

    # Weighted by empirical importance for celestial footage noise patterns.
    score = 0.20 * np.abs(z_brightness) + 0.20 * np.abs(z_edge) + 0.25 * np.abs(z_hot) + 0.35 * np.abs(z_motion)

    anomalies: List[FrameAnomaly] = []
    for i, (frame_idx, timestamp, _brightness, edges, hot_pixels, motion) in enumerate(frame_rows):
        if score[i] < anomaly_z_threshold:
            continue
        anomalies.append(
            FrameAnomaly(
                source_file=str(path),
                frame_index=frame_idx,
                timestamp_sec=timestamp,
                score=float(score[i]),
                motion_score=motion,
                brightness_z=float(z_brightness[i]),
                hot_pixel_ratio=hot_pixels,
                edge_density=edges,
            )
        )

    return sorted(anomalies, key=lambda x: x.score, reverse=True)


def write_outputs(anomalies: Sequence[FrameAnomaly], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "anomalies.csv"
    json_path = out_dir / "anomalies.json"

    fieldnames = list(asdict(anomalies[0]).keys()) if anomalies else list(FrameAnomaly.__annotations__.keys())

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in anomalies:
            writer.writerow(asdict(row))

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in anomalies], f, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect anomalous astrophotography frames.")
    parser.add_argument("input", type=Path, help="Input file or directory containing images/videos")
    parser.add_argument("--output", type=Path, default=Path("data/staging/processed/celestial_anomalies"))
    parser.add_argument("--frame-step", type=int, default=5, help="Analyze every Nth video frame")
    parser.add_argument("--threshold", type=float, default=2.5, help="Composite anomaly score threshold")
    parser.add_argument("--top", type=int, default=500, help="Max anomalies to keep globally")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = collect_media_files(args.input)
    if not files:
        print(f"No supported media files found at: {args.input}")
        return 1

    all_anomalies: List[FrameAnomaly] = []
    failed_files: List[str] = []

    for path in files:
        try:
            anomalies = analyze_file(path, frame_step=args.frame_step, anomaly_z_threshold=args.threshold)
            all_anomalies.extend(anomalies)
            print(f"{path}: scanned, anomalies={len(anomalies)}")
        except Exception as exc:
            failed_files.append(str(path))
            print(f"{path}: error: {exc}")

    all_anomalies.sort(key=lambda x: x.score, reverse=True)
    all_anomalies = all_anomalies[: max(args.top, 0)]
    write_outputs(all_anomalies, args.output)

    summary = {
        "files_scanned": len(files),
        "files_failed": len(failed_files),
        "failed_file_paths": failed_files,
        "anomalies_written": len(all_anomalies),
        "threshold": args.threshold,
        "frame_step": args.frame_step,
        "generated_at_epoch": time.time(),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {len(all_anomalies)} anomalies to {args.output}")
    return 0 if len(failed_files) < len(files) else 2


if __name__ == "__main__":
    raise SystemExit(main())
