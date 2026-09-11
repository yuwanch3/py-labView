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

    return header + payload[:, :, ::-1].tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare normal read() against grab/retrieve "
            "for freshest DroidCam frame."
        )
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
        "--grab-count",
        type=int,
        default=3,
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

    print("DroidCam Freshness Comparison")
    print("============================")
    print(f"Source     : {args.url}")
    print(f"UI poll    : {args.interval_ms} ms")
    print(f"Grab count : {args.grab_count}")
    print()
    print("Press SPACE to switch mode.")
    print("Mode READ = normal capture.read()")
    print("Mode FRESH = grab stale frames, then retrieve latest")
    print()
    print("Move your hand normally and compare both modes.")

    capture = cv2.VideoCapture(
        args.url
    )

    if not capture.isOpened():
        capture.release()
        raise SystemExit(
            "ERROR: camera could not be opened"
        )

    if hasattr(
        cv2,
        "CAP_PROP_BUFFERSIZE",
    ):
        try:
            capture.set(
                cv2.CAP_PROP_BUFFERSIZE,
                1,
            )
        except Exception:
            pass

    root = tk.Tk()

    root.title(
        "DroidCam Freshness Test"
    )

    canvas = tk.Canvas(
        root,
        width=args.width,
        height=args.height,
        background="black",
    )

    canvas.pack()

    status = tk.Label(
        root,
        text="",
        font=("TkDefaultFont", 11),
    )

    status.pack()

    state = {
        "running": True,
        "mode": "READ",
        "image": None,
        "canvas_image": None,
        "frames": 0,
        "started": time.perf_counter(),
        "last_read_ms": 0.0,
    }

    def stop() -> None:
        state["running"] = False

        try:
            capture.release()
        except Exception:
            pass

        root.destroy()

    def toggle_mode(_event=None) -> None:
        if state["mode"] == "READ":
            state["mode"] = "FRESH"
        else:
            state["mode"] = "READ"

        state["frames"] = 0
        state["started"] = time.perf_counter()

        print(
            f"Switched to {state['mode']} mode"
        )

    root.protocol(
        "WM_DELETE_WINDOW",
        stop,
    )

    root.bind(
        "<space>",
        toggle_mode,
    )

    def get_frame():
        start = time.perf_counter()

        if state["mode"] == "READ":
            ok, payload = capture.read()

        else:
            ok = True

            for _ in range(
                args.grab_count
            ):
                ok = capture.grab()

                if not ok:
                    break

            if ok:
                ok, payload = capture.retrieve()
            else:
                payload = None

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000.0

        state["last_read_ms"] = (
            elapsed_ms
        )

        return ok, payload

    def update_frame() -> None:
        if not state["running"]:
            return

        try:
            ok, payload = get_frame()

            if (
                not ok
                or payload is None
            ):
                print(
                    "Camera frame failed"
                )

                root.after(
                    args.interval_ms,
                    update_frame,
                )

                return

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

            fps = (
                state["frames"] / elapsed
                if elapsed > 0
                else 0.0
            )

            status.config(
                text=(
                    f"MODE: {state['mode']} | "
                    f"FPS: {fps:.1f} | "
                    f"capture: "
                    f"{state['last_read_ms']:.1f} ms | "
                    "SPACE = switch"
                )
            )

            root.title(
                f"DroidCam Freshness "
                f"| {state['mode']}"
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