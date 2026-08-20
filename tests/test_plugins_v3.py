import unittest
from unittest.mock import patch

from pylabview.model import NODE_DEFINITIONS, NodeDefinition
from pylabview.plugins import PluginManifest, PluginRegistry


class EntryPoints:
    def __init__(self, entries): self.entries = entries
    def select(self, **_kwargs): return self.entries


class Entry:
    def __init__(self, name, factory): self.name, self.factory = name, factory
    def load(self): return self.factory


class GoodPlugin:
    manifest = PluginManifest("example.good", "1.0")
    def activate(self, registry):
        registry.register_node("example.good.node", NodeDefinition("Example", "Plugin"), lambda *_args: 7)


class IncompatiblePlugin:
    manifest = PluginManifest("example.old", "1.0", api_version=99)
    def activate(self, _registry): raise AssertionError("must not activate")


class PluginV3Tests(unittest.TestCase):
    def tearDown(self):
        NODE_DEFINITIONS.pop("example.good.node", None)
        NODE_DEFINITIONS.pop("example.duplicate", None)

    def test_plugin_node_must_be_namespaced(self):
        with self.assertRaises(ValueError): PluginRegistry().register_node("plain", NodeDefinition("X", "X"))

    def test_duplicate_node_is_rejected(self):
        registry = PluginRegistry()
        registry.register_node("example.duplicate", NodeDefinition("X", "X"))
        with self.assertRaises(ValueError): registry.register_node("example.duplicate", NodeDefinition("X", "X"))

    @patch("pylabview.plugins.metadata.entry_points")
    def test_compatible_plugin_is_activated(self, entry_points):
        entry_points.return_value = EntryPoints([Entry("good", GoodPlugin)])
        registry = PluginRegistry(); statuses = registry.discover()
        self.assertEqual(statuses[-1].state, "active"); self.assertIn("example.good.node", registry.node_definitions)

    @patch("pylabview.plugins.metadata.entry_points")
    def test_incompatible_plugin_is_isolated(self, entry_points):
        entry_points.return_value = EntryPoints([Entry("old", IncompatiblePlugin)])
        status = PluginRegistry().discover()[-1]
        self.assertEqual(status.state, "incompatible")

    @patch("pylabview.plugins.metadata.entry_points")
    def test_import_failure_does_not_abort_discovery(self, entry_points):
        class BrokenEntry(Entry):
            def load(self): raise ImportError("missing dependency")
        entry_points.return_value = EntryPoints([BrokenEntry("broken", None)])
        status = PluginRegistry().discover()[-1]
        self.assertEqual(status.state, "failed"); self.assertIn("missing dependency", status.message)


if __name__ == "__main__": unittest.main()
