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


def summarize(name: str, values_ms: list[float]) -> None:
    if not values_ms:
        print(f"{name}: no data")
        return

    print()
    print(name)
    print("-" * len(name))
    print(f"Samples : {len(values_ms)}")
    print(f"Mean    : {statistics.mean(values_ms):.3f} ms")
    print(f"Median  : {statistics.median(values_ms):.3f} ms")
    print(f"P95     : {percentile(values_ms, 95):.3f} ms")
    print(f"P99     : {percentile(values_ms, 99):.3f} ms")
    print(f"Max     : {max(values_ms):.3f} ms")


def fingerprint(payload) -> int:
    array = np.asarray(payload)

    if array.size == 0:
        return 0

    height = array.shape[0]
    width = array.shape[1]

    y1 = height // 4
    y2 = height - y1
    x1 = width // 4
    x2 = width - x1

    roi = array[y1:y2:8, x1:x2:8]

    return zlib.crc32(roi.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark PyLabView internal production camera worker."
    )

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--poll-ms",
        type=float,
        default=77.0,
        help="Polling interval, matching PyLabView UI refresh approximately.",
    )

    args = parser.parse_args()

    print("PyLabView Internal Production Camera Worker Benchmark")
    print("====================================================")
    print(f"Source   : {args.url}")
    print(f"Duration : {args.duration:.1f} s")
    print(f"Timeout  : {args.timeout:.1f} s")
    print(f"Poll     : {args.poll_ms:.1f} ms")

    vision = VisionAdapter(cv2, np)

    key = (
        "network",
        args.url,
    )

    print()
    print("Creating production _CameraWorker...")

    worker = vision._get_or_create_worker(
        key=key,
        source=args.url,
    )

    print("Waiting for first frame...")

    first_start = time.perf_counter()

    try:
        first_payload = worker.get_frame(
            args.timeout
        )
    except Exception as exc:
        vision.release_all_captures()
        raise SystemExit(
            f"ERROR waiting for first frame: {exc}"
        )

    first_end = time.perf_counter()

    print(
        f"First frame latency : "
        f"{(first_end - first_start) * 1000.0:.3f} ms"
    )

    worker_latencies_ms: list[float] = []
    returned_intervals_ms: list[float] = []
    fingerprints: list[int] = []

    failures = 0
    frames = 0

    fingerprints.append(
        fingerprint(first_payload)
    )

    previous_return_time = first_end

    print()
    print("Benchmark started.")
    print("Move your hand continuously in front of DroidCam.")

    start = time.perf_counter()
    deadline = start + args.duration

    try:
        while time.perf_counter() < deadline:
            call_start = time.perf_counter()

            try:
                payload = worker.get_frame(
                    args.timeout
                )
            except Exception as exc:
                failures += 1
                print(f"Worker error: {exc}")
                time.sleep(args.poll_ms / 1000.0)
                continue

            call_end = time.perf_counter()

            worker_latencies_ms.append(
                (call_end - call_start) * 1000.0
            )

            returned_intervals_ms.append(
                (call_end - previous_return_time) * 1000.0
            )

            previous_return_time = call_end

            fingerprints.append(
                fingerprint(payload)
            )

            frames += 1

            time.sleep(
                args.poll_ms / 1000.0
            )

    finally:
        vision.release_all_captures()

    end = time.perf_counter()

    elapsed = end - start

    returned_rate = (
        frames / elapsed
        if elapsed > 0
        else 0.0
    )

    repeated = 0
    longest_repeat = 1
    current_repeat = 1

    for previous, current in zip(
        fingerprints,
        fingerprints[1:],
    ):
        if previous == current:
            repeated += 1
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

    repeated_percent = (
        repeated / comparisons * 100.0
        if comparisons
        else 0.0
    )

    print()
    print("RESULT")
    print("======")
    print(f"Elapsed              : {elapsed:.3f} s")
    print(f"Frames returned      : {frames}")
    print(f"Failures             : {failures}")
    print(f"Return rate          : {returned_rate:.3f} calls/s")
    print(f"Repeated fingerprints: {repeated}")
    print(f"Repeated percentage  : {repeated_percent:.2f}%")
    print(f"Longest repeat run   : {longest_repeat}")

    summarize(
        "worker.get_frame() latency",
        worker_latencies_ms,
    )

    summarize(
        "Returned-frame interval",
        returned_intervals_ms,
    )

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()