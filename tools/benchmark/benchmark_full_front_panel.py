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

    # Add some content so this is not an empty image.
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
        description=(
            "Benchmark complete production PanelDesigner.redraw() "
            "using the real spinning-drop Standard project."
        )
    )

    parser.add_argument(
        "--project",
        default="examples/spinning_drop_ift.json",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
    )

    args = parser.parse_args()

    project_path = Path(
        args.project
    )

    print("PyLabView Full Front Panel Benchmark")
    print("====================================")
    print(f"Project    : {project_path}")
    print(f"Iterations : {args.iterations}")

    project = load_project(
        project_path
    )

    vi = project.main

    graph = vi.graph
    panel_data = vi.front_panel

    print(
        f"Canvas     : "
        f"{panel_data['canvas']['width']}x"
        f"{panel_data['canvas']['height']}"
    )

    print(
        f"Panel items: "
        f"{len(panel_data['items'])}"
    )

    root = tk.Tk()

    root.title(
        "PyLabView Full Front Panel Benchmark"
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

    # ------------------------------------------------------------
    # Representative runtime values
    # ------------------------------------------------------------

    frame = make_test_frame()

    values = {
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

    # ------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------

    print()
    print("Warm-up...")

    panel.values.update(
        values
    )

    for _ in range(5):
        panel.redraw()
        root.update_idletasks()

    # ------------------------------------------------------------
    # Benchmark redraw() directly
    # ------------------------------------------------------------

    redraw_times: list[float] = []

    print()
    print("Benchmarking PanelDesigner.redraw()...")

    for _ in range(
        args.iterations
    ):
        start = time.perf_counter()

        panel.redraw()

        root.update_idletasks()

        end = time.perf_counter()

        redraw_times.append(
            (end - start) * 1000.0
        )

    summarize(
        "Full PanelDesigner.redraw()",
        redraw_times,
    )

    redraw_mean = statistics.mean(
        redraw_times
    )

    print()
    print("REFERENCE")
    print("=========")

    print(
        f"Target UI interval     : 77.000 ms"
    )

    print(
        f"Mean full redraw       : "
        f"{redraw_mean:.3f} ms"
    )

    print(
        f"Interval usage         : "
        f"{redraw_mean / 77.0 * 100.0:.1f}%"
    )

    print(
        f"Theoretical redraw FPS : "
        f"{1000.0 / redraw_mean:.2f}"
    )

    if redraw_mean > 77.0:
        print(
            "Assessment             : "
            "REDRAW EXCEEDS UI BUDGET"
        )
    elif redraw_mean > 50.0:
        print(
            "Assessment             : "
            "REDRAW IS HEAVY"
        )
    else:
        print(
            "Assessment             : "
            "REDRAW IS WITHIN UI BUDGET"
        )

    print()
    print(
        "Close the benchmark window "
        "or press Ctrl+C if needed."
    )

    root.destroy()

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()