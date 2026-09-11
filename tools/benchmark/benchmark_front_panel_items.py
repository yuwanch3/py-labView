from __future__ import annotations

import argparse
import statistics
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np

from pylabview.front_panel import PanelDesigner
from pylabview.integrations.vision_adapter import ImageFrame
from pylabview.persistence import load_project


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


def make_test_frame(
    width: int = 640,
    height: int = 480,
) -> ImageFrame:
    payload = np.zeros(
        (
            height,
            width,
            3,
        ),
        dtype=np.uint8,
    )

    cv2.rectangle(
        payload,
        (80, 80),
        (560, 400),
        (255, 255, 255),
        3,
    )

    cv2.circle(
        payload,
        (320, 240),
        80,
        (180, 180, 180),
        -1,
    )

    return ImageFrame(
        payload,
        width,
        height,
        3,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark individual PyLabView front-panel items."
    )

    parser.add_argument(
        "--project",
        default="examples/spinning_drop_ift.json",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
    )

    args = parser.parse_args()

    project = load_project(
        Path(args.project)
    )

    vi = project.main
    graph = vi.graph
    panel_data = vi.front_panel

    print("PyLabView Front Panel Item Benchmark")
    print("====================================")
    print(f"Project    : {args.project}")
    print(f"Iterations : {args.iterations}")
    print(f"Panel items: {len(panel_data['items'])}")

    root = tk.Tk()

    root.title(
        "PyLabView Front Panel Item Benchmark"
    )

    root.geometry(
        "1200x800"
    )

    panel = PanelDesigner(
        root,
        graph,
        panel_data,
    )

    panel.pack(
        fill="both",
        expand=True,
    )

    panel.set_mode(
        "operate"
    )

    root.update()

    frame = make_test_frame()

    panel.values.update(
        {
            "motor": True,
            "rpm_display": 2000.0,
            "pwm_display": 120.0,
            "com": "COM4",
            "wifi": "http://192.168.0.6:4747/video/force/1280x720",
            "time_display_1": 38.5,
            "time_display_2": 38.5,

            "oil_picture": frame,
            "wire_picture": frame,

            "oil_px_display": 32.0,
            "oil_mm_display": 0.5,
            "density_input": 150.0,

            "wire_px_display": 32.0,
            "scale_display": 0.015625,

            "omega_display": 43864.9,
            "radius_display": 1.5625e-11,
            "ift_n_display": 0.00257,
            "ift_mn_display": 2.57,

            "oil_chart": [
                float(
                    128
                    + 100
                    * np.sin(
                        index / 30.0
                    )
                )
                for index in range(500)
            ],

            "wire_chart": [
                float(
                    128
                    + 80
                    * np.cos(
                        index / 25.0
                    )
                )
                for index in range(500)
            ],

            "table_display": [
                [
                    "RPM",
                    "Dia px",
                    "Dia mm",
                    "kg/m3",
                    "w²",
                    "r³",
                    "IFT N/m",
                    "IFT mN/m",
                ],
                [
                    1000,
                    32,
                    0.5,
                    150,
                    10966.2,
                    1.5625e-11,
                    0.00064,
                    0.64,
                ],
                [
                    2000,
                    32,
                    0.5,
                    150,
                    43864.9,
                    1.5625e-11,
                    0.00257,
                    2.57,
                ],
            ],

            "capture_wire": False,
            "global_stop": False,

            "oil_mode": "network",
            "oil_source": 0,
            "wire_known": 0.5,
            "oil_orientation": "horizontal",
            "wire_orientation": "horizontal",
            "cam_timeout": 5.0,
            "capture_oil": True,

            "density_mode": "Manual Δρ",
            "fluid_1": "Water",
            "density_1": 1000.0,
            "fluid_2": "Oil",
            "density_2": 850.0,
        }
    )

    root.update_idletasks()

    results: list[
        tuple[
            float,
            float,
            float,
            str,
            str,
            str,
        ]
    ] = []

    print()
    print("Benchmarking each item...")

    for item in sorted(
        panel_data["items"],
        key=lambda entry: entry["z_index"],
    ):
        times: list[float] = []

        for _ in range(
            args.iterations
        ):
            panel.delete(
                "all"
            )

            panel._image_refs.clear()

            start = time.perf_counter()

            panel._draw_item(
                item
            )

            root.update_idletasks()

            end = time.perf_counter()

            times.append(
                (end - start) * 1000.0
            )

        mean_ms = statistics.mean(
            times
        )

        p95_ms = percentile(
            times,
            95,
        )

        max_ms = max(
            times
        )

        label = item[
            "properties"
        ].get(
            "label",
            item["kind"],
        )

        results.append(
            (
                mean_ms,
                p95_ms,
                max_ms,
                item["id"],
                item["kind"],
                label,
            )
        )

    results.sort(
        reverse=True,
        key=lambda row: row[0],
    )

    print()
    print("RESULTS - slowest first")
    print("=======================")

    print(
        f"{'Mean ms':>9} "
        f"{'P95 ms':>9} "
        f"{'Max ms':>9} "
        f"{'Kind':<20} "
        f"{'ID':<24} "
        f"Label"
    )

    print(
        "-" * 100
    )

    for (
        mean_ms,
        p95_ms,
        max_ms,
        item_id,
        kind,
        label,
    ) in results:

        print(
            f"{mean_ms:9.3f} "
            f"{p95_ms:9.3f} "
            f"{max_ms:9.3f} "
            f"{kind:<20} "
            f"{item_id:<24} "
            f"{label}"
        )

    total_mean = sum(
        result[0]
        for result in results
    )

    print()
    print("SUMMARY")
    print("=======")
    print(
        f"Sum of per-item means : "
        f"{total_mean:.3f} ms"
    )

    print(
        f"77 ms budget usage    : "
        f"{total_mean / 77.0 * 100.0:.1f}%"
    )

    root.destroy()

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()