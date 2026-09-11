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


def image_to_ppm_fast(frame) -> bytes:
    payload = np.asarray(frame.payload)

    if payload.dtype != np.uint8:
        raise ValueError(
            "front-panel thumbnails require uint8 images"
        )

    if frame.width * frame.height > 1_000_000:
        raise ValueError(
            "front-panel thumbnail source exceeds processing bound"
        )

    if frame.channels == 1:
        header = (
            f"P5\n{frame.width} {frame.height}\n255\n"
        ).encode("ascii")

        return header + payload.tobytes()

    if frame.channels == 3:
        header = (
            f"P6\n{frame.width} {frame.height}\n255\n"
        ).encode("ascii")

        # OpenCV/ImageFrame payload is BGR.
        # PPM requires RGB.
        rgb = payload[:, :, ::-1]

        return header + rgb.tobytes()

    raise ValueError(
        f"unsupported channel count: {frame.channels}"
    )


def benchmark(
    function,
    frame,
    iterations: int,
) -> tuple[list[float], bytes]:

    times_ms: list[float] = []
    result = b""

    for _ in range(iterations):
        start = time.perf_counter()

        result = function(frame)

        end = time.perf_counter()

        times_ms.append(
            (end - start) * 1000.0
        )

    return times_ms, result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare production image_to_ppm() "
            "against NumPy fast conversion."
        )
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

    print("PyLabView image_to_ppm Fast Comparison")
    print("======================================")

    vision = VisionAdapter(
        cv2,
        np,
    )

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

        print()
        print("Warm-up...")

        production_ppm = image_to_ppm(frame)
        fast_ppm = image_to_ppm_fast(frame)

        identical = (
            production_ppm == fast_ppm
        )

        print(
            f"Byte-identical output : {identical}"
        )

        print(
            f"Production bytes      : "
            f"{len(production_ppm):,}"
        )

        print(
            f"Fast bytes            : "
            f"{len(fast_ppm):,}"
        )

        if not identical:
            mismatch = None

            limit = min(
                len(production_ppm),
                len(fast_ppm),
            )

            for index in range(limit):
                if (
                    production_ppm[index]
                    != fast_ppm[index]
                ):
                    mismatch = index
                    break

            print(
                f"First mismatch index   : {mismatch}"
            )

            raise SystemExit(
                "STOP: fast output is not identical "
                "to production output."
            )

        print()
        print(
            f"Running {args.iterations} production conversions..."
        )

        production_times, production_result = benchmark(
            image_to_ppm,
            frame,
            args.iterations,
        )

        print(
            f"Running {args.iterations} fast conversions..."
        )

        fast_times, fast_result = benchmark(
            image_to_ppm_fast,
            frame,
            args.iterations,
        )

    finally:
        vision.release_all_captures()

    if production_result != fast_result:
        raise SystemExit(
            "ERROR: benchmark outputs differ."
        )

    summarize(
        "Production image_to_ppm()",
        production_times,
    )

    summarize(
        "Fast NumPy image_to_ppm_fast()",
        fast_times,
    )

    production_mean = statistics.mean(
        production_times
    )

    fast_mean = statistics.mean(
        fast_times
    )

    speedup = (
        production_mean / fast_mean
        if fast_mean > 0
        else 0.0
    )

    print()
    print("COMPARISON")
    print("==========")
    print(
        f"Production mean : "
        f"{production_mean:.3f} ms"
    )
    print(
        f"Fast mean       : "
        f"{fast_mean:.3f} ms"
    )
    print(
        f"Speed-up        : "
        f"{speedup:.1f}x"
    )

    print()
    print(
        f"Production uses : "
        f"{production_mean / 77.0 * 100.0:.1f}% "
        f"of 77 ms interval"
    )

    print(
        f"Fast uses       : "
        f"{fast_mean / 77.0 * 100.0:.1f}% "
        f"of 77 ms interval"
    )

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()