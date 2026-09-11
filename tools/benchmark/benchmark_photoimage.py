from __future__ import annotations

import argparse
import statistics
import time
import tkinter as tk

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


def summarize(name: str, values: list[float]) -> None:
    print()
    print(name)
    print("-" * len(name))
    print(f"Samples : {len(values)}")
    print(f"Mean    : {statistics.mean(values):.3f} ms")
    print(f"Median  : {statistics.median(values):.3f} ms")
    print(f"P95     : {percentile(values, 95):.3f} ms")
    print(f"P99     : {percentile(values, 99):.3f} ms")
    print(f"Max     : {max(values):.3f} ms")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--width",
        type=int,
        default=400,
    )

    parser.add_argument(
        "--height",
        type=int,
        default=300,
    )

    args = parser.parse_args()

    print("PyLabView Tkinter PhotoImage Benchmark")
    print("======================================")

    vision = VisionAdapter(
        cv2,
        np,
    )

    root = tk.Tk()

    root.title(
        "PyLabView Tkinter Benchmark"
    )

    canvas = tk.Canvas(
        root,
        width=args.width,
        height=args.height,
    )

    canvas.pack()

    root.update()

    try:
        print()
        print("Waiting for camera frame...")

        frame = vision.capture_source(
            "network",
            0,
            args.url,
            args.timeout,
        )

        # --------------------------------------------------------
        # We only need one frame for the UI benchmark.
        # Stop camera worker immediately so FFmpeg/background
        # capture cannot interfere with the Tkinter measurements.
        # --------------------------------------------------------

        vision.release_all_captures()

        print(
            f"Frame : "
            f"{frame.width}x{frame.height}x{frame.channels}"
        )

        ppm = image_to_ppm(
            frame
        )

        print(
            f"PPM   : {len(ppm):,} bytes"
        )

        ppm_times: list[float] = []
        photo_times: list[float] = []
        subsample_times: list[float] = []
        canvas_times: list[float] = []
        total_times: list[float] = []

        image_ref = None

        print()
        print("Benchmark started...")

        for _ in range(
            args.iterations
        ):
            total_start = (
                time.perf_counter()
            )

            # ----------------------------------------
            # image_to_ppm
            # ----------------------------------------

            start = time.perf_counter()

            ppm = image_to_ppm(
                frame
            )

            end = time.perf_counter()

            ppm_times.append(
                (end - start) * 1000.0
            )

            # ----------------------------------------
            # PhotoImage
            # ----------------------------------------

            start = time.perf_counter()

            image = tk.PhotoImage(
                data=ppm,
                format="PPM",
            )

            end = time.perf_counter()

            photo_times.append(
                (end - start) * 1000.0
            )

            # ----------------------------------------
            # Same scaling strategy as production
            # ----------------------------------------

            scale_x = (
                image.width()
                / max(
                    args.width - 12,
                    1,
                )
            )

            scale_y = (
                image.height()
                / max(
                    args.height - 30,
                    1,
                )
            )

            scale = max(
                1,
                int(
                    np.ceil(
                        max(
                            scale_x,
                            scale_y,
                        )
                    )
                ),
            )

            start = time.perf_counter()

            if scale > 1:
                image = image.subsample(
                    scale,
                    scale,
                )

            end = time.perf_counter()

            subsample_times.append(
                (end - start) * 1000.0
            )

            # ----------------------------------------
            # Simulate production canvas recreation
            # ----------------------------------------

            start = time.perf_counter()

            canvas.delete(
                "all"
            )

            canvas.create_rectangle(
                0,
                0,
                args.width,
                args.height,
            )

            canvas.create_text(
                8,
                10,
                text="Picture Oil",
                anchor="w",
            )

            canvas.create_image(
                args.width / 2,
                args.height / 2,
                image=image,
            )

            image_ref = image

            root.update_idletasks()

            end = time.perf_counter()

            canvas_times.append(
                (end - start) * 1000.0
            )

            total_end = (
                time.perf_counter()
            )

            total_times.append(
                (
                    total_end
                    - total_start
                )
                * 1000.0
            )

    finally:
        # Safe even if capture was already released above.
        vision.release_all_captures()

        root.destroy()

    summarize(
        "image_to_ppm()",
        ppm_times,
    )

    summarize(
        "tk.PhotoImage()",
        photo_times,
    )

    summarize(
        "PhotoImage.subsample()",
        subsample_times,
    )

    summarize(
        "Canvas delete/create/update",
        canvas_times,
    )

    summarize(
        "TOTAL image UI path",
        total_times,
    )

    total_mean = statistics.mean(
        total_times
    )

    print()
    print("REFERENCE")
    print("=========")

    print(
        f"77 ms target interval : "
        f"{77.0:.3f} ms"
    )

    print(
        f"UI path mean          : "
        f"{total_mean:.3f} ms"
    )

    print(
        f"Interval usage        : "
        f"{total_mean / 77.0 * 100.0:.1f}%"
    )

    print(
        f"Theoretical FPS       : "
        f"{1000.0 / total_mean:.2f}"
    )

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()