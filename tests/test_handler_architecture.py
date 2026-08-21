import inspect
import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

from pylabview.execution import RunSession
from pylabview.handlers import BUILTIN_HANDLERS, HandlerContext, HandlerRegistry
from pylabview.model import Graph, NODE_DEFINITIONS, Node, Project
from pylabview.plugins import DEFAULT_PLUGIN_REGISTRY, PluginRegistry
from pylabview.resources import ResourceManager
from pylabview.runtime import DataflowError, DataflowRuntime


class HandlerRegistryTests(unittest.TestCase):
    def test_builtin_registry_is_complete(self):
        self.assertEqual(BUILTIN_HANDLERS.audit(NODE_DEFINITIONS), (set(), set()))

    def test_builtin_handlers_are_owned_by_handler_modules(self):
        for handler in BUILTIN_HANDLERS.handlers().values():
            self.assertTrue(handler.__module__.startswith("pylabview.handlers."), handler)

    def test_registry_rejects_duplicate_registration(self):
        registry = HandlerRegistry()
        registry.register("sample")(lambda _context: 1)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("sample")(lambda _context: 2)

    def test_unknown_node_is_explicit(self):
        node = Node("unknown", "missing.node", 0, 0, "Unknown")
        with self.assertRaisesRegex(DataflowError, "unknown node type"):
            DataflowRuntime()._evaluate(node, {}, {}, [])

    def test_dynamic_plugin_fallback(self):
        node_type = "test.dynamic.handler"
        DEFAULT_PLUGIN_REGISTRY.evaluators[node_type] = lambda node, inputs, session: inputs["value"] + 1
        try:
            node = Node("plugin", node_type, 0, 0, "Plugin")
            self.assertEqual(DataflowRuntime()._evaluate(node, {"value": 4}, {}, []), 5)
        finally:
            DEFAULT_PLUGIN_REGISTRY.evaluators.pop(node_type, None)

    def test_handler_context_exposes_execution_dependencies(self):
        runtime = DataflowRuntime()
        session = RunSession(resources=ResourceManager())
        node = Node("n", "numeric_constant", 0, 0, "N", {"value": 1})
        context = HandlerContext(runtime, node, {}, {}, [], None, None, session, "standalone")
        self.assertEqual((context.runtime, context.node, context.session, context.graph_scope),
                          (runtime, node, session, "standalone"))

    def test_runtime_accepts_an_independent_registry(self):
        registry = HandlerRegistry()
        registry.register("numeric_constant")(lambda _context: 41)
        graph = Graph()
        node = graph.add_node("numeric_constant")
        self.assertEqual(DataflowRuntime(handler_registry=registry).run(graph).values[node.id], 41)

    def test_runtime_accepts_an_independent_plugin_registry(self):
        node_type = "test.global.plugin"
        DEFAULT_PLUGIN_REGISTRY.evaluators[node_type] = lambda *_args: "global"
        try:
            runtime = DataflowRuntime(handler_registry=HandlerRegistry(), plugin_registry=PluginRegistry())
            node = Node("plugin", node_type, 0, 0, "Plugin")
            with self.assertRaisesRegex(DataflowError, "unknown node type"):
                runtime._evaluate(node, {}, {}, [])
        finally:
            DEFAULT_PLUGIN_REGISTRY.evaluators.pop(node_type, None)

    def test_evaluate_is_registry_dispatch_only(self):
        source = inspect.getsource(DataflowRuntime._evaluate)
        self.assertLessEqual(len(source.splitlines()), 40)
        self.assertNotIn("node.type ==", source)
        tree = ast.parse(textwrap.dedent(source))
        self.assertEqual(len([node for node in ast.walk(tree) if isinstance(node, ast.If)]), 1)
        self.assertFalse(any(isinstance(node, ast.Match) for node in ast.walk(tree)))

    def test_public_parsers_are_short(self):
        self.assertLessEqual(len(inspect.getsource(Graph.from_dict).splitlines()), 15)
        self.assertLessEqual(len(inspect.getsource(Project.from_dict).splitlines()), 15)

    def test_build_ui_is_short(self):
        source = Path(__file__).parents[1].joinpath("pylabview", "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        method = next(item for item in next(item for item in tree.body if isinstance(item, ast.ClassDef)
                                             and item.name == "StudioApp").body
                      if isinstance(item, ast.FunctionDef) and item.name == "_build_ui")
        self.assertLessEqual(method.end_lineno - method.lineno + 1, 30)

    def test_no_legacy_implementations_remain(self):
        root = Path(__file__).parents[1].joinpath("pylabview")
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            legacy = [node.name for node in ast.walk(tree)
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.name.startswith("_legacy_")]
            self.assertEqual(legacy, [], str(path))

    def test_frozen_specs_include_dynamic_handler_modules(self):
        root = Path(__file__).parents[1]
        modules = {f"pylabview.handlers.{name}" for name in
                   ("core_math", "collections", "structures", "sync", "io", "instrumentation",
                    "vision", "network", "project")}
        modules.add("pylabview.handlers.spinning_drop")
        for filename in ("PyLabViewStudio.spec", "PyLabViewStudioFull.spec"):
            source = root.joinpath(filename).read_text(encoding="utf-8")
            self.assertEqual({module for module in modules if module not in source}, set(), filename)

    def test_core_math_handler_behavior(self):
        graph = Graph(); a = graph.add_node("numeric_constant"); b = graph.add_node("numeric_constant"); add = graph.add_node("add")
        a.properties["value"], b.properties["value"] = 2, 5
        graph.connect(a.id, "out", add.id, "a"); graph.connect(b.id, "out", add.id, "b")
        self.assertEqual(DataflowRuntime().run(graph).values[add.id], 7)

    def test_collection_handler_behavior(self):
        runtime = DataflowRuntime(); node = Node("n", "array_build", 0, 0, "Array")
        self.assertEqual(runtime._evaluate(node, {"a": [1], "b": 2}, {}, []), [1, 2])

    def test_structure_handler_behavior(self):
        runtime = DataflowRuntime(); node = Node("n", "case", 0, 0, "Case")
        self.assertEqual(runtime._evaluate(node, {"selector": False, "true": 1, "false": 2}, {}, []), 2)

    def test_file_handler_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "value.txt").write_text("value", encoding="utf-8")
            node = Node("n", "file_read", 0, 0, "Read", {"path": "value.txt"})
            self.assertEqual(DataflowRuntime(data_root=directory)._evaluate(node, {}, {}, [])["text"], "value")

    def test_sync_handlers_are_registered(self):
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("queue_create"))
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("event_wait"))

    def test_network_handlers_are_registered(self):
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("tcp_connect"))
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("udp_receive"))

    def test_instrumentation_handlers_are_registered(self):
        for node_type in ("analog_input", "serial_open", "visa_query", "opcua_read",
                          "modbus_read_coils", "modbus_write_registers"):
            self.assertIsNotNone(BUILTIN_HANDLERS.resolve(node_type))

    def test_vision_handlers_are_registered(self):
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("camera_capture"))
        self.assertIsNotNone(BUILTIN_HANDLERS.resolve("template_match"))

    def test_project_handler_subvi_behavior(self):
        project = Project(); node = project.main.graph.add_node("numeric_constant"); node.properties["value"] = 9
        self.assertEqual(DataflowRuntime().run_project(project).values[node.id], 9)


if __name__ == "__main__":
    unittest.main()
