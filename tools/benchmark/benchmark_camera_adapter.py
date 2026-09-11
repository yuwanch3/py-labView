from __future__ import annotations

import argparse
import statistics
import time
import zlib

import cv2
import numpy as np

from pylabview.integrations.vision_adapter import VisionAdapter


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


def summarize(name: str, values: list[float]) -> None:
    if not values:
        print(f"{name}: no data")
        return

    print()
    print(name)
    print("-" * len(name))
    print(f"Samples : {len(values)}")
    print(f"Mean    : {statistics.mean(values):.3f} ms")
    print(f"Median  : {statistics.median(values):.3f} ms")
    print(f"P95     : {percentile(values, 95):.3f} ms")
    print(f"P99     : {percentile(values, 99):.3f} ms")
    print(f"Max     : {max(values):.3f} ms")


def frame_fingerprint(frame) -> int:
    payload = np.asarray(frame.payload)

    if payload.size == 0:
        return 0

    height = payload.shape[0]
    width = payload.shape[1]

    # Ambil area tengah dan downsample supaya fingerprint murah.
    y1 = height // 4
    y2 = height - y1
    x1 = width // 4
    x2 = width - x1

    roi = payload[y1:y2:8, x1:x2:8]

    return zlib.crc32(roi.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark PyLabView production VisionAdapter."
    )

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
        help="DroidCam/network camera URL.",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Measurement duration in seconds.",
    )

    parser.add_argument(
        "--warmup",
        type=float,
        default=3.0,
        help="Warm-up duration in seconds.",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="VisionAdapter camera timeout.",
    )

    args = parser.parse_args()

    print("PyLabView VisionAdapter Camera Benchmark")
    print("========================================")
    print(f"Source   : {args.url}")
    print(f"Warm-up  : {args.warmup:.1f} s")
    print(f"Duration : {args.duration:.1f} s")
    print()
    print("IMPORTANT:")
    print("During the benchmark, move your hand in front of")
    print("the phone camera several times.")
    print("This helps detect repeated/stale frames.")
    print()

    vision = VisionAdapter(cv2, np)

    call_times_ms: list[float] = []
    intervals_ms: list[float] = []

    fingerprints: list[int] = []

    successful_frames = 0
    failed_frames = 0

    previous_time: float | None = None

    try:
        print("Warming up VisionAdapter...")

        warmup_end = time.perf_counter() + args.warmup

        while time.perf_counter() < warmup_end:
            vision.capture_source(
                "network",
                0,
                args.url,
                args.timeout,
            )

        print("Benchmark started.")
        print("Wave/move your hand in front of DroidCam now.\n")

        start = time.perf_counter()
        deadline = start + args.duration

        while time.perf_counter() < deadline:
            call_start = time.perf_counter()

            try:
                frame = vision.capture_source(
                    "network",
                    0,
                    args.url,
                    args.timeout,
                )
            except Exception as exc:
                failed_frames += 1
                print(f"Capture error: {exc}")
                continue

            call_end = time.perf_counter()

            if frame is None:
                failed_frames += 1
                continue

            successful_frames += 1

            call_ms = (call_end - call_start) * 1000.0
            call_times_ms.append(call_ms)

            fingerprints.append(
                frame_fingerprint(frame)
            )

            if previous_time is not None:
                intervals_ms.append(
                    (call_end - previous_time) * 1000.0
                )

            previous_time = call_end

        end = time.perf_counter()

    finally:
        vision.release_all_captures()

    elapsed = end - start

    fps = (
        successful_frames / elapsed
        if elapsed > 0
        else 0.0
    )

    duplicate_count = 0
    longest_repeat = 1
    current_repeat = 1

    for previous, current in zip(
        fingerprints,
        fingerprints[1:],
    ):
        if current == previous:
            duplicate_count += 1
            current_repeat += 1
            longest_repeat = max(
                longest_repeat,
                current_repeat,
            )
        else:
            current_repeat = 1

    comparisons = max(
        len(fingerprints) - 1,
        0,
    )

    duplicate_percent = (
        duplicate_count / comparisons * 100.0
        if comparisons
        else 0.0
    )

    print()
    print("RESULT")
    print("======")
    print(f"Elapsed              : {elapsed:.3f} s")
    print(f"Successful frames    : {successful_frames}")
    print(f"Failed frames        : {failed_frames}")
    print(f"Adapter call rate    : {fps:.3f} calls/s")
    print(f"Repeated fingerprints: {duplicate_count}")
    print(f"Repeated percentage  : {duplicate_percent:.2f}%")
    print(f"Longest repeat run   : {longest_repeat} frames")

    summarize(
        "VisionAdapter capture_source() latency",
        call_times_ms,
    )

    summarize(
        "Returned-frame interval",
        intervals_ms,
    )

    print()
    print("Interpretation guide")
    print("--------------------")
    print("Low call latency + many repeats:")
    print("  Adapter is responsive, but same/latest frame")
    print("  may be returned repeatedly.")
    print()
    print("High call latency:")
    print("  Camera worker / capture path may be blocking.")
    print()
    print("Low repeats while hand is moving:")
    print("  Latest-frame delivery is probably healthy.")
    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()