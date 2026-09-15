from __future__ import annotations

import sys


def self_test() -> int:
    from . import __version__
    from .model import Graph, Project
    from .persistence import load_project
    from .plugins import DEFAULT_PLUGIN_REGISTRY
    from .protocols import OPCUA_CAPABILITIES
    from .runtime import DataflowRuntime

    project = Project("Self Test")
    source = project.main.graph.add_node("numeric_constant")
    source.properties["value"] = 3
    restored = Project.from_dict(project.to_dict())
    result = DataflowRuntime().run_project(restored)
    if __version__ != "3.0.0" or result.errors or result.values[source.id] != 3:
        raise RuntimeError("core model/runtime self-test failed")
    if "add" not in DEFAULT_PLUGIN_REGISTRY.node_definitions:
        raise RuntimeError("builtin plugin registry self-test failed")
    if OPCUA_CAPABILITIES.available:
        raise RuntimeError("core must not claim an unavailable OPC UA adapter")
    print(f"PyLabView Studio {__version__} self-test OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    from .app import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
