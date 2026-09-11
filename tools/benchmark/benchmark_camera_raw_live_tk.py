from __future__ import annotations

import argparse
import math
import time
import tkinter as tk

import cv2


def frame_to_ppm(payload) -> bytes:
    height, width = payload.shape[:2]

    header = (
        f"P6\n{width} {height}\n255\n"
    ).encode("ascii")

    # OpenCV BGR -> PPM RGB
    return header + payload[:, :, ::-1].tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Raw OpenCV DroidCam visual latency test."
    )

    parser.add_argument(
        "--url",
        default="http://192.168.0.6:4747/video/force/1280x720",
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

    print("Raw OpenCV DroidCam Live Tkinter Test")
    print("=====================================")
    print(f"Source  : {args.url}")
    print(f"UI poll : {args.interval_ms} ms")
    print()
    print("Compare this window directly with the phone.")
    print("Move your hand quickly or cover/uncover the lens.")
    print()

    print("Opening raw VideoCapture...")

    open_start = time.perf_counter()

    capture = cv2.VideoCapture(
        args.url
    )

    if not capture.isOpened():
        capture.release()
        raise SystemExit(
            "ERROR: camera could not be opened"
        )

    print(
        "VideoCapture opened in "
        f"{(time.perf_counter() - open_start) * 1000:.1f} ms"
    )

    print("Waiting for first raw frame...")

    first_start = time.perf_counter()

    ok, payload = capture.read()

    if not ok or payload is None:
        capture.release()
        raise SystemExit(
            "ERROR: camera did not return first frame"
        )

    print(
        "First read latency: "
        f"{(time.perf_counter() - first_start) * 1000:.1f} ms"
    )

    print(
        f"Frame: "
        f"{payload.shape[1]}x{payload.shape[0]}"
    )

    root = tk.Tk()

    root.title(
        "RAW OpenCV DroidCam Live Test"
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
            capture.release()
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
            read_start = time.perf_counter()

            ok, payload = capture.read()

            read_ms = (
                time.perf_counter()
                - read_start
            ) * 1000.0

            if not ok or payload is None:
                print(
                    "Raw capture failed."
                )

                root.after(
                    args.interval_ms,
                    update_frame,
                )

                return

            height, width = (
                payload.shape[:2]
            )

            ppm = frame_to_ppm(
                payload
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
                        / max(args.width, 1),
                        image.height()
                        / max(args.height, 1),
                    )
                ),
            )

            if scale > 1:
                image = image.subsample(
                    scale,
                    scale,
                )

            state["image"] = image

            if state["canvas_image"] is None:
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

            fps = (
                state["frames"] / elapsed
                if elapsed > 0
                else 0.0
            )

            root.title(
                "RAW OpenCV DroidCam "
                f"| {fps:.1f} FPS "
                f"| read {read_ms:.1f} ms"
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

    print()
    print("Test complete.")


if __name__ == "__main__":
    main()