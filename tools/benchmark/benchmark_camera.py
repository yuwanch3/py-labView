from __future__ import annotations

import argparse
import statistics
import time
from collections import deque

import cv2


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

    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(name: str, values_ms: list[float]) -> None:
    if not values_ms:
        print(f"{name}: no data")
        return

    print(f"\n{name}")
    print("-" * len(name))
    print(f"Samples : {len(values_ms)}")
    print(f"Mean    : {statistics.mean(values_ms):.3f} ms")
    print(f"Median  : {statistics.median(values_ms):.3f} ms")
    print(f"P95     : {percentile(values_ms, 95):.3f} ms")
    print(f"P99     : {percentile(values_ms, 99):.3f} ms")
    print(f"Max     : {max(values_ms):.3f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Camera acquisition benchmark for PyLabView."
    )
    parser.add_argument(
        "--source",
        default="http://192.168.0.6:4747/video/force/1280x720",
        help="OpenCV camera index or DroidCam/network URL.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Benchmark duration in seconds.",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=3.0,
        help="Warm-up duration before measurements.",
    )
    parser.add_argument(
        "--stall-ms",
        type=float,
        default=250.0,
        help="Frame read time considered a stall.",
    )
    args = parser.parse_args()

    source: str | int = args.source

    try:
        source = int(source)
    except ValueError:
        pass

    print("PyLabView Camera Benchmark")
    print("==========================")
    print(f"Source   : {source}")
    print(f"Warm-up  : {args.warmup:.1f} s")
    print(f"Duration : {args.duration:.1f} s")

    capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        raise SystemExit(f"ERROR: cannot open camera source: {source}")

    try:
        print("\nWarming up camera...")

        warmup_deadline = time.perf_counter() + args.warmup

        while time.perf_counter() < warmup_deadline:
            ok, _frame = capture.read()

            if not ok:
                raise SystemExit("ERROR: camera read failed during warm-up")

        print("Benchmark started.\n")

        read_times_ms: list[float] = []
        frame_intervals_ms: list[float] = []
        recent_intervals = deque(maxlen=120)

        successful_frames = 0
        failed_reads = 0
        stalls = 0

        benchmark_start = time.perf_counter()
        deadline = benchmark_start + args.duration

        previous_frame_time: float | None = None

        while time.perf_counter() < deadline:
            read_start = time.perf_counter()

            ok, frame = capture.read()

            read_end = time.perf_counter()
            read_ms = (read_end - read_start) * 1000.0

            if not ok or frame is None:
                failed_reads += 1
                continue

            successful_frames += 1
            read_times_ms.append(read_ms)

            if read_ms >= args.stall_ms:
                stalls += 1

            if previous_frame_time is not None:
                interval_ms = (read_end - previous_frame_time) * 1000.0
                frame_intervals_ms.append(interval_ms)
                recent_intervals.append(interval_ms)

            previous_frame_time = read_end

        benchmark_end = time.perf_counter()
        elapsed = benchmark_end - benchmark_start

    finally:
        capture.release()

    fps = successful_frames / elapsed if elapsed > 0 else 0.0

    print("RESULT")
    print("======")
    print(f"Elapsed           : {elapsed:.3f} s")
    print(f"Successful frames : {successful_frames}")
    print(f"Failed reads      : {failed_reads}")
    print(f"Measured FPS      : {fps:.3f}")
    print(f"Stalls >= {args.stall_ms:.0f} ms : {stalls}")

    summarize("Camera read() latency", read_times_ms)
    summarize("Frame interval", frame_intervals_ms)

    if frame_intervals_ms:
        expected_interval = 1000.0 / fps if fps > 0 else 0.0
        slow_frames = sum(
            1
            for value in frame_intervals_ms
            if expected_interval > 0 and value > expected_interval * 2.0
        )

        print("\nFrame timing")
        print("------------")
        print(f"Average FPS interval : {expected_interval:.3f} ms")
        print(f">2x interval frames  : {slow_frames}")

    print("\nBenchmark complete.")


if __name__ == "__main__":
    main()