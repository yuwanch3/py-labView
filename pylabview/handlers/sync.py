from __future__ import annotations

from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


def _resource(context: HandlerContext, kind: str, create):
    return context.runtime._session_resource(context.session, context.caller_vi, context.node,
                                             kind, context.graph_scope, create)


@registry.register("queue_create")
def queue_create(context: HandlerContext):
    return _resource(context, "queue", lambda: context.session.resources.create_queue(
        context.runtime._bounded_int(context.node, "capacity", 100),
        str(context.node.properties.get("type_name", "variant"))))


@registry.register("queue_put")
def queue_put(context: HandlerContext):
    queue = context.session.resources.get(context.inputs["queue"], "queue")
    queue.put(context.inputs["value"], float(context.node.properties.get("timeout", 1)), context.session.token)
    return context.inputs["queue"]


@registry.register("queue_get")
def queue_get(context: HandlerContext):
    return context.session.resources.get(context.inputs["queue"], "queue").get(
        float(context.node.properties.get("timeout", 1)), context.session.token)


@registry.register("notifier_create")
def notifier_create(context: HandlerContext):
    return _resource(context, "notifier", context.session.resources.create_notifier)


@registry.register("notifier_set")
def notifier_set(context: HandlerContext):
    return context.session.resources.get(context.inputs["notifier"], "notifier").set(context.inputs["value"])


@registry.register("notifier_wait")
def notifier_wait(context: HandlerContext):
    value, generation = context.session.resources.get(context.inputs["notifier"], "notifier").wait(
        int(context.inputs["generation"]), float(context.node.properties.get("timeout", 1)), context.session.token)
    return {"value": value, "generation": generation}


@registry.register("event_create")
def event_create(context: HandlerContext):
    return _resource(context, "event", lambda: context.session.resources.create_event(
        str(context.node.properties.get("name", "event"))))


@registry.register("event_fire")
def event_fire(context: HandlerContext):
    return context.session.resources.get(context.inputs["event"], "event").fire(context.inputs["value"])


@registry.register("event_wait")
def event_wait(context: HandlerContext):
    value, generation = context.session.resources.get(context.inputs["event"], "event").wait(
        int(context.inputs["generation"]), float(context.node.properties.get("timeout", 1)), context.session.token)
    return {"value": value, "generation": generation}


@registry.register("channel_create")
def channel_create(context: HandlerContext):
    return _resource(context, "channel", lambda: context.session.resources.create_channel(
        context.runtime._bounded_int(context.node, "capacity", 100),
        str(context.node.properties.get("type_name", "variant"))))


@registry.register("channel_send")
def channel_send(context: HandlerContext):
    channel = context.session.resources.get(context.inputs["channel"], "channel")
    channel.put(context.inputs["value"], float(context.node.properties.get("timeout", 1)), context.session.token)
    return context.inputs["channel"]


@registry.register("channel_receive")
def channel_receive(context: HandlerContext):
    return context.session.resources.get(context.inputs["channel"], "channel").get(
        float(context.node.properties.get("timeout", 1)), context.session.token)


@registry.register("resource_close")
def resource_close(context: HandlerContext):
    context.session.resources.close(context.inputs["resource"])
    return None
