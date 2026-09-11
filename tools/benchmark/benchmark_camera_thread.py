from __future__ import annotations

import argparse
import statistics
import threading
import time

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

    print()
    print(name)
    print("-" * len(name))
    print(f"Samples : {len(values_ms)}")
    print(f"Mean    : {statistics.mean(values_ms):.3f} ms")
    print(f"Median  : {statistics.median(values_ms):.3f} ms")
    print(f"P95     : {percentile(values_ms, 95):.3f} ms")
    print(f"P99     : {percentile(values_ms, 99):.3f} ms")
    print(f"Max     : {max(values_ms):.3f} ms")


class CameraThread:
    def __init__(self, source: str | int):
        self.source = source
        self.stop_event = threading.Event()

        self.read_times_ms: list[float] = []
        self.frame_intervals_ms: list[float] = []

        self.successful_frames = 0
        self.failed_reads = 0

        self.opened = False
        self.error: Exception | None = None

        self.thread = threading.Thread(
            target=self._worker,
            name="camera-benchmark-thread",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5.0)

    def _worker(self) -> None:
        capture = None

        try:
            # Important:
            # VideoCapture is created INSIDE the worker thread.
            # This imitates the important threading characteristic
            # of the PyLabView camera worker.
            capture = cv2.VideoCapture(self.source)

            if not capture.isOpened():
                raise OSError(f"cannot open camera source: {self.source}")

            self.opened = True

            previous_frame_time: float | None = None

            while not self.stop_event.is_set():
                read_start = time.perf_counter()

                ok, frame = capture.read()

                read_end = time.perf_counter()

                read_ms = (read_end - read_start) * 1000.0

                if not ok or frame is None:
                    self.failed_reads += 1
                    continue

                self.successful_frames += 1
                self.read_times_ms.append(read_ms)

                if previous_frame_time is not None:
                    self.frame_intervals_ms.append(
                        (read_end - previous_frame_time) * 1000.0
                    )

                previous_frame_time = read_end

        except Exception as exc:
            self.error = exc

        finally:
            if capture is not None:
                capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenCV camera benchmark using a background thread."
    )

    parser.add_argument(
        "--source",
        default="http://192.168.0.6:4747/video/force/1280x720",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--warmup",
        type=float,
        default=3.0,
    )

    args = parser.parse_args()

    source: str | int = args.source

    try:
        source = int(source)
    except ValueError:
        pass

    print("PyLabView Background Camera Thread Benchmark")
    print("============================================")
    print(f"Source   : {source}")
    print(f"Warm-up  : {args.warmup:.1f} s")
    print(f"Duration : {args.duration:.1f} s")

    camera = CameraThread(source)

    print()
    print("Starting background camera thread...")

    camera.start()

    startup_deadline = time.perf_counter() + 10.0

    while not camera.opened:
        if camera.error is not None:
            raise SystemExit(f"ERROR: {camera.error}")

        if time.perf_counter() >= startup_deadline:
            camera.stop()
            raise SystemExit("ERROR: camera did not open within 10 seconds")

        time.sleep(0.01)

    print("Camera opened.")
    print("Warming up...")

    warmup_start_count = camera.successful_frames
    warmup_deadline = time.perf_counter() + args.warmup

    while time.perf_counter() < warmup_deadline:
        if camera.error is not None:
            camera.stop()
            raise SystemExit(f"ERROR during warm-up: {camera.error}")

        time.sleep(0.05)

    warmup_frames = camera.successful_frames - warmup_start_count

    # Reset statistics so only the measurement interval is reported.
    camera.read_times_ms.clear()
    camera.frame_intervals_ms.clear()
    camera.successful_frames = 0
    camera.failed_reads = 0

    print(f"Warm-up frames: {warmup_frames}")
    print("Benchmark started.")

    start = time.perf_counter()
    deadline = start + args.duration

    try:
        while time.perf_counter() < deadline:
            if camera.error is not None:
                raise RuntimeError(
                    f"background camera thread failed: {camera.error}"
                )

            time.sleep(0.05)

    finally:
        camera.stop()

    end = time.perf_counter()
    elapsed = end - start

    fps = (
        camera.successful_frames / elapsed
        if elapsed > 0
        else 0.0
    )

    stalls = sum(
        1
        for value in camera.read_times_ms
        if value >= 250.0
    )

    print()
    print("RESULT")
    print("======")
    print(f"Elapsed           : {elapsed:.3f} s")
    print(f"Successful frames : {camera.successful_frames}")
    print(f"Failed reads      : {camera.failed_reads}")
    print(f"Measured FPS      : {fps:.3f}")
    print(f"Stalls >= 250 ms  : {stalls}")

    summarize(
        "Background read() latency",
        camera.read_times_ms,
    )

    summarize(
        "Background frame interval",
        camera.frame_intervals_ms,
    )

    if camera.error is not None:
        print()
        print(f"Worker error: {camera.error}")

    print()
    print("Benchmark complete.")


if __name__ == "__main__":
    main()