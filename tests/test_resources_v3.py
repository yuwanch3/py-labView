import threading
import time
import unittest

from pylabview.execution import CancellationToken, CancelledError
from pylabview.resources import ResourceError, ResourceManager


class ResourceV3Tests(unittest.TestCase):
    def setUp(self):
        self.manager = ResourceManager(); self.token = CancellationToken()

    def tearDown(self): self.manager.close_all()

    def test_queue_is_fifo(self):
        ref = self.manager.create_queue(2); queue = self.manager.get(ref, "queue")
        queue.put("a", 0.1, self.token); queue.put("b", 0.1, self.token)
        self.assertEqual([queue.get(0.1, self.token), queue.get(0.1, self.token)], ["a", "b"])

    def test_bounded_queue_times_out_when_full(self):
        queue = self.manager.get(self.manager.create_queue(1), "queue"); queue.put(1, 0.1, self.token)
        with self.assertRaises(TimeoutError): queue.put(2, 0.02, self.token)

    def test_queue_wait_is_cancelled(self):
        queue = self.manager.get(self.manager.create_queue(1), "queue")
        threading.Timer(0.02, self.token.cancel).start()
        with self.assertRaises(CancelledError): queue.get(1, self.token)

    def test_close_wakes_queue_waiter(self):
        ref = self.manager.create_queue(1); queue = self.manager.get(ref, "queue")
        threading.Timer(0.02, lambda: self.manager.close(ref)).start()
        with self.assertRaises(ResourceError): queue.get(1, self.token)

    def test_typed_queue_rejects_wrong_value(self):
        queue = self.manager.get(self.manager.create_queue(1, "boolean"), "queue")
        with self.assertRaises(TypeError): queue.put(1, 0.1, self.token)

    def test_notifier_returns_latest_generation(self):
        notifier = self.manager.get(self.manager.create_notifier(), "notifier")
        self.assertEqual(notifier.set("first"), 1); notifier.set("latest")
        self.assertEqual(notifier.wait(1, 0.1, self.token), ("latest", 2))

    def test_named_event_is_reused(self):
        first = self.manager.create_event("ready"); second = self.manager.create_event("ready")
        self.assertEqual(first, second)

    def test_event_payload_and_generation(self):
        event = self.manager.get(self.manager.create_event("data"), "event")
        event.fire({"x": 2})
        self.assertEqual(event.wait(0, 0.1, self.token), ({"x": 2}, 1))

    def test_message_channel_is_fifo(self):
        channel = self.manager.get(self.manager.create_channel(2, "numeric"), "channel")
        channel.put(3, 0.1, self.token); channel.put(4, 0.1, self.token)
        self.assertEqual(channel.get(0.1, self.token), 3)
        self.assertEqual(channel.get(0.1, self.token), 4)

    def test_cross_manager_reference_is_rejected(self):
        ref = self.manager.create_queue(1)
        with self.assertRaises(ResourceError): ResourceManager().get(ref)

    def test_double_close_is_rejected(self):
        ref = self.manager.create_queue(1); self.manager.close(ref)
        with self.assertRaises(ResourceError): self.manager.close(ref)

    def test_real_producer_consumer_with_backpressure(self):
        queue = self.manager.get(self.manager.create_queue(2, "numeric"), "queue"); consumed = []
        def producer():
            for value in range(20): queue.put(value, 1, self.token)
        def consumer():
            for _ in range(20): consumed.append(queue.get(1, self.token))
        threads = [threading.Thread(target=producer), threading.Thread(target=consumer)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads)); self.assertEqual(consumed, list(range(20)))


if __name__ == "__main__": unittest.main()
