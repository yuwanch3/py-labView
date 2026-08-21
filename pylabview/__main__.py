from __future__ import annotations

import sys
from multiprocessing import freeze_support


def _isolated_self_test(payload: object) -> object:
    return payload


def self_test(include_isolation: bool = True) -> int:
    from . import __version__
    from .model import Graph, Project
    from .persistence import load_project
    from .plugins import DEFAULT_PLUGIN_REGISTRY
    from .integrations.opcua_adapter import OpcUaAdapter
    from .integrations.isolation import IsolatedEvaluatorHost
    from .runtime import DataflowRuntime

    project = Project("Self Test")
    source = project.main.graph.add_node("numeric_constant")
    source.properties["value"] = 3
    restored = Project.from_dict(project.to_dict())
    result = DataflowRuntime().run_project(restored)
    if __version__ != "4.3.0" or result.errors or result.values[source.id] != 3:
        raise RuntimeError("core model/runtime self-test failed")
    if "add" not in DEFAULT_PLUGIN_REGISTRY.node_definitions:
        raise RuntimeError("builtin plugin registry self-test failed")
    OpcUaAdapter().available  # Capability probing must never crash when asyncua is absent.
    if include_isolation:
        with IsolatedEvaluatorHost("pylabview.__main__:_isolated_self_test") as host:
            if host.call({"core": True}, 10) != {"core": True}:
                raise RuntimeError("core process isolation self-test failed")
    print(f"PyLabView Studio {__version__} self-test OK")
    return 0


def self_test_full() -> int:
    from importlib import import_module
    from tempfile import TemporaryDirectory
    from pathlib import Path

    for module in ("nidaqmx", "pyvisa", "serial", "asyncua.sync", "cv2", "numpy",
                   "openpyxl", "docx", "reportlab"):
        import_module(module)
    from .integrations.isolation import IsolatedEvaluatorHost
    from .integrations.reports_adapter import ReportsAdapter
    from .integrations.vision_adapter import VisionAdapter

    with IsolatedEvaluatorHost("pylabview.__main__:_isolated_self_test") as host:
        if host.call({"safe": True}, 10) != {"safe": True}:
            raise RuntimeError("isolated evaluator self-test failed")
    numpy = import_module("numpy")
    frame = VisionAdapter().grayscale(VisionAdapter._frame(numpy.zeros((2, 3, 3), dtype=numpy.uint8)))
    if (frame.width, frame.height, frame.channels) != (3, 2, 1):
        raise RuntimeError("vision self-test failed")
    with TemporaryDirectory(prefix="pylabview-full-self-test-") as directory:
        report = ReportsAdapter().generate([["safe", 1]], Path(directory) / "report.html", "html")
        if not report.is_file(): raise RuntimeError("report self-test failed")
    self_test()
    print("PyLabView Studio full optional profile self-test OK")
    return 0


def main() -> int:
    freeze_support()
    if "--self-test-full" in sys.argv[1:]:
        return self_test_full()
    if "--self-test-frozen" in sys.argv[1:]:
        return self_test(include_isolation=False)
    if "--self-test" in sys.argv[1:]:
        return self_test()
    from .app import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
