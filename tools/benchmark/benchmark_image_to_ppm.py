from __future__ import annotations

import argparse
import statistics
import time

import cv2
import numpy as np

from pylabview.integrations.vision_adapter import VisionAdapter
from pylabview.panel_widgets import image_to_ppm


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * (percent / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower

    return ordered[lower] + (
        ordered[upper] - ordered[lower]
    ) * fraction


def summarize(name: str, values_ms: list[float]) -> None:
    print()
    print(name)
    print("-" * len(name))
    print(f"Samples : {len(values_ms)}")
    print(f"Mean    : {statistics.mean(values_ms):.3f} ms")
    print(f"Median  : {statistics.median(values_ms):.3f} ms")
    print(f"P95     : {percentile(values_ms, 95):.3f} ms")
    print(f"P99     : {percentile(values_ms, 99):.3f} ms")
    print(f"Max     : {max(values_ms):.3f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark production image_to_ppm() conversion."
    )

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
    )

    args = parser.parse_args()

    print("PyLabView image_to_ppm Benchmark")
    print("===============================")
    print(f"Source     : {args.url}")
    print(f"Iterations : {args.iterations}")

    vision = VisionAdapter(cv2, np)

    try:
        print()
        print("Waiting for camera frame...")

        frame = vision.capture_source(
            "network",
            0,
            args.url,
            args.timeout,
        )

        print(
            f"Frame      : "
            f"{frame.width}x{frame.height}x{frame.channels}"
        )

        print(
            f"Pixels     : "
            f"{frame.width * frame.height:,}"
        )

        # Warm-up
        print("Warming up conversion...")

        for _ in range(3):
            ppm = image_to_ppm(frame)

        print(
            f"PPM bytes  : "
            f"{len(ppm):,}"
        )

        times_ms: list[float] = []

        print()
        print("Benchmark started...")

        for _ in range(args.iterations):
            start = time.perf_counter()

            ppm = image_to_ppm(frame)

            end = time.perf_counter()

            times_ms.append(
                (end - start) * 1000.0
            )

    finally:
        vision.release_all_captures()

    summarize(
        "image_to_ppm() latency",
        times_ms,
    )

    mean_ms = statistics.mean(times_ms)

    theoretical_fps = (
        1000.0 / mean_ms
        if mean_ms > 0
        else 0.0
    )

    print()
    print("Throughput")
    print("----------")
    print(
        f"Conversion-only theoretical FPS : "
        f"{theoretical_fps:.2f}"
    )

    print()
    print("Reference")
    print("---------")
    print("PyLabView UI refresh target : ~77 ms")
    print(
        f"Mean conversion consumes    : "
        f"{mean_ms / 77.0 * 100.0:.1f}% "
        f"of one 77 ms UI interval"
    )

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()