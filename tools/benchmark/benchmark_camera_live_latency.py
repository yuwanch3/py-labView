from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from pylabview.integrations.vision_adapter import VisionAdapter


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Visual latency test for PyLabView production camera worker."
        )
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
        "--poll-ms",
        type=float,
        default=10.0,
    )

    args = parser.parse_args()

    print("PyLabView Production Camera Live Latency Test")
    print("=============================================")
    print(f"Source  : {args.url}")
    print(f"Timeout : {args.timeout:.1f} s")
    print()
    print("Press Q or ESC to stop.")
    print("Move your hand quickly in front of DroidCam.")
    print("Compare the PC window against the phone preview.")

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

    start = time.perf_counter()

    try:
        frame = worker.get_frame(
            args.timeout
        )
    except Exception as exc:
        vision.release_all_captures()
        raise SystemExit(
            f"ERROR waiting for first frame: {exc}"
        )

    elapsed = (
        time.perf_counter()
        - start
    ) * 1000.0

    print(
        f"First frame latency: "
        f"{elapsed:.1f} ms"
    )

    frames = 0
    start_live = time.perf_counter()

    try:
        while True:
            try:
                frame = worker.get_frame(
                    args.timeout
                )
            except Exception as exc:
                print(
                    f"Camera error: {exc}"
                )
                break

            frames += 1

            now = time.perf_counter()
            elapsed_live = now - start_live

            fps = (
                frames / elapsed_live
                if elapsed_live > 0
                else 0.0
            )

            display = frame.copy()

            cv2.putText(
                display,
                f"Production Worker | Display FPS: {fps:.1f}",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                display,
                "Move hand quickly - compare latency with phone",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow(
                "PyLabView Production Camera Live Latency",
                display,
            )

            key_pressed = cv2.waitKey(
                max(
                    1,
                    int(args.poll_ms),
                )
            ) & 0xFF

            if key_pressed in (
                27,
                ord("q"),
                ord("Q"),
            ):
                break

    finally:
        vision.release_all_captures()
        cv2.destroyAllWindows()

    print()
    print("Test complete.")


if __name__ == "__main__":
    main()