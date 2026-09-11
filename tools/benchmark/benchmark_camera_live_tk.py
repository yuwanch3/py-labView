from __future__ import annotations

import argparse
import math
import time
import tkinter as tk

import cv2
import numpy as np

from pylabview.integrations.vision_adapter import VisionAdapter, ImageFrame
from pylabview.panel_widgets import image_to_ppm


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visual live-latency test for production camera worker."
    )

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--interval-ms",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--width",
        type=int,
        default=640,
    )

    parser.add_argument(
        "--height",
        type=int,
        default=480,
    )

    args = parser.parse_args()

    print("PyLabView Production Camera Live Tkinter Test")
    print("=============================================")
    print(f"Source   : {args.url}")
    print(f"Timeout  : {args.timeout:.1f} s")
    print(f"UI poll  : {args.interval_ms} ms")
    print()
    print("Move your hand quickly in front of DroidCam.")
    print("Compare this window against the phone preview.")
    print("Close the window to stop.")

    vision = VisionAdapter(
        cv2,
        np,
    )

    key = (
        "network",
        args.url,
    )

    worker = vision._get_or_create_worker(
        key=key,
        source=args.url,
    )

    print()
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

    first_ms = (
        time.perf_counter()
        - first_start
    ) * 1000.0

    print(
        f"First frame latency: {first_ms:.1f} ms"
    )

    root = tk.Tk()
    root.title(
        "PyLabView Camera Worker Live Test"
    )

    canvas = tk.Canvas(
        root,
        width=args.width,
        height=args.height,
        background="black",
    )

    canvas.pack()

    state = {
        "running": True,
        "image": None,
        "canvas_image": None,
        "frames": 0,
        "started": time.perf_counter(),
    }

    def stop() -> None:
        state["running"] = False

        try:
            vision.release_all_captures()
        except Exception:
            pass

        root.destroy()

    root.protocol(
        "WM_DELETE_WINDOW",
        stop,
    )

    def update_frame() -> None:
        if not state["running"]:
            return

        try:
            payload = worker.get_frame(
                args.timeout
            )

            height = int(
                payload.shape[0]
            )

            width = int(
                payload.shape[1]
            )

            channels = (
                1
                if payload.ndim == 2
                else int(payload.shape[2])
            )

            frame = ImageFrame(
                payload,
                width,
                height,
                channels,
            )

            ppm = image_to_ppm(
                frame
            )

            image = tk.PhotoImage(
                data=ppm,
                format="PPM",
            )

            scale = max(
                1,
                math.ceil(
                    max(
                        image.width()
                        / max(
                            args.width,
                            1,
                        ),
                        image.height()
                        / max(
                            args.height,
                            1,
                        ),
                    )
                ),
            )

            if scale > 1:
                image = image.subsample(
                    scale,
                    scale,
                )

            state["image"] = image

            if (
                state["canvas_image"]
                is None
            ):
                state["canvas_image"] = (
                    canvas.create_image(
                        args.width / 2,
                        args.height / 2,
                        image=image,
                    )
                )

            else:
                canvas.itemconfigure(
                    state["canvas_image"],
                    image=image,
                )

            state["frames"] += 1

            elapsed = (
                time.perf_counter()
                - state["started"]
            )

            if elapsed > 0:
                fps = (
                    state["frames"]
                    / elapsed
                )

                root.title(
                    "PyLabView Camera Worker Live Test "
                    f"| {fps:.1f} FPS"
                )

        except Exception as exc:
            print(
                f"Frame error: {exc}"
            )

        if state["running"]:
            root.after(
                args.interval_ms,
                update_frame,
            )

    root.after(
        0,
        update_frame,
    )

    root.mainloop()

    try:
        vision.release_all_captures()
    except Exception:
        pass

    print()
    print("Test complete.")


if __name__ == "__main__":
    main()