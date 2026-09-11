from __future__ import annotations

import statistics
import time

from pylabview.execution import RunController
from pylabview.model import Graph


class DummyRuntime:
    """Minimal runtime used only to measure RunController scheduling cadence."""

    def run(
        self,
        graph,
        controls,
        project,
        vi_id,
        session=None,
        debug=False,
        graph_scope=None,
    ):
        # Simulate a very fast runtime iteration.
        return {
            "completed_at": time.monotonic(),
        }


def run_case(interval: float, duration: float = 3.0) -> None:
    controller = RunController(DummyRuntime())

    # RunController.start() always clones the supplied graph, so it must be
    # a real Graph object even though DummyRuntime does not use its contents.
    graph = Graph("RunController Interval Benchmark")

    controller.start(
        graph=graph,
        controls={},
        project=None,
        vi_id=None,
        continuous=True,
        interval=interval,
    )

    timestamps = []
    started = time.monotonic()

    try:
        while time.monotonic() - started < duration:
            for event in controller.drain_events():
                if event.kind == "result":
                    timestamps.append(event.timestamp)

            time.sleep(0.002)

    finally:
        controller.stop()
        controller.join(2.0)

    intervals_ms = [
        (b - a) * 1000.0
        for a, b in zip(timestamps, timestamps[1:])
    ]

    print(f"\ninterval argument = {interval:.3f} s")
    print(f"result events     = {len(timestamps)}")

    if not intervals_ms:
        print("not enough result events")
        return

    mean_ms = statistics.mean(intervals_ms)

    print(f"mean cadence      = {mean_ms:.3f} ms")
    print(f"median cadence    = {statistics.median(intervals_ms):.3f} ms")
    print(f"min cadence       = {min(intervals_ms):.3f} ms")
    print(f"max cadence       = {max(intervals_ms):.3f} ms")
    print(f"approx result FPS = {1000.0 / mean_ms:.2f}")


if __name__ == "__main__":
    print("RunController interval benchmark v2")
    print("This does NOT use camera, motor, serial, Standard Mode, or Manual Mode.")
    print("It only measures the scheduler wait inside RunController.")

    run_case(0.150)
    run_case(0.060)
    run_case(0.010)
