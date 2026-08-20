import unittest

from pylabview.model import Graph
from pylabview.runtime import DataflowRuntime


def constant(graph, kind, value):
    node = graph.add_node(kind); node.properties["value"] = value; return node


class SynchronizationNodeTests(unittest.TestCase):
    def test_queue_nodes_exchange_one_message(self):
        graph = Graph(); create = graph.add_node("queue_create"); value = constant(graph, "string_constant", "message")
        put, get = graph.add_node("queue_put"), graph.add_node("queue_get")
        graph.connect(create.id, "out", put.id, "queue"); graph.connect(value.id, "out", put.id, "value")
        graph.connect(create.id, "out", get.id, "queue")
        result = DataflowRuntime(max_workers=2).run(graph)
        self.assertFalse(result.errors); self.assertEqual(result.values[get.id], "message")

    def test_notifier_nodes_report_generation(self):
        graph = Graph(); create = graph.add_node("notifier_create"); value = constant(graph, "numeric_constant", 12)
        generation = constant(graph, "numeric_constant", 0); set_node, wait = graph.add_node("notifier_set"), graph.add_node("notifier_wait")
        graph.connect(create.id, "out", set_node.id, "notifier"); graph.connect(value.id, "out", set_node.id, "value")
        graph.connect(create.id, "out", wait.id, "notifier"); graph.connect(generation.id, "out", wait.id, "generation")
        result = DataflowRuntime(max_workers=2).run(graph)
        self.assertFalse(result.errors); self.assertEqual(result.values[wait.id], {"value": 12, "generation": 1})

    def test_named_event_nodes_deliver_payload(self):
        graph = Graph(); create = graph.add_node("event_create"); payload = constant(graph, "string_constant", "ready")
        generation = constant(graph, "numeric_constant", 0); fire, wait = graph.add_node("event_fire"), graph.add_node("event_wait")
        graph.connect(create.id, "out", fire.id, "event"); graph.connect(payload.id, "out", fire.id, "value")
        graph.connect(create.id, "out", wait.id, "event"); graph.connect(generation.id, "out", wait.id, "generation")
        result = DataflowRuntime(max_workers=2).run(graph)
        self.assertFalse(result.errors); self.assertEqual(result.values[wait.id]["value"], "ready")

    def test_channel_nodes_preserve_message(self):
        graph = Graph(); create = graph.add_node("channel_create"); value = constant(graph, "boolean_constant", True)
        send, receive = graph.add_node("channel_send"), graph.add_node("channel_receive")
        graph.connect(create.id, "out", send.id, "channel"); graph.connect(value.id, "out", send.id, "value")
        graph.connect(create.id, "out", receive.id, "channel")
        result = DataflowRuntime(max_workers=2).run(graph)
        self.assertFalse(result.errors); self.assertTrue(result.values[receive.id])


if __name__ == "__main__": unittest.main()
