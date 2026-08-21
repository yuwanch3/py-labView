from __future__ import annotations

from ..protocols import TcpConnection, UdpEndpoint
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


def _resource(context: HandlerContext, kind: str, create):
    return context.runtime._session_resource(context.session, context.caller_vi, context.node,
                                             kind, context.graph_scope, create)


@registry.register("tcp_connect")
def tcp_connect(context: HandlerContext):
    return _resource(context, "tcp", lambda: context.session.resources.add("tcp", TcpConnection.connect(
        str(context.node.properties.get("host", "127.0.0.1")), context.node.properties.get("port", 502),
        float(context.node.properties.get("timeout", 2)), context.session.token)))


@registry.register("tcp_read")
def tcp_read(context: HandlerContext):
    connection = context.session.resources.get(context.inputs["connection"], "tcp")
    return connection.read(int(context.node.properties.get("size", 1024)),
                           float(context.node.properties.get("timeout", 2)), context.session.token,
                           str(context.node.properties.get("mode", "up_to")),
                           bytes.fromhex(str(context.node.properties.get("delimiter_hex", "0a"))))


@registry.register("tcp_write")
def tcp_write(context: HandlerContext):
    return context.session.resources.get(context.inputs["connection"], "tcp").write(
        context.inputs["data"], float(context.node.properties.get("timeout", 2)), context.session.token)


@registry.register("udp_open")
def udp_open(context: HandlerContext):
    return _resource(context, "udp", lambda: context.session.resources.add("udp", UdpEndpoint.open(
        str(context.node.properties.get("host", "127.0.0.1")), context.node.properties.get("port", 0),
        float(context.node.properties.get("timeout", 2)))))


@registry.register("udp_send")
def udp_send(context: HandlerContext):
    return context.session.resources.get(context.inputs["endpoint"], "udp").send(
        context.inputs["data"], str(context.node.properties.get("host", "127.0.0.1")),
        context.node.properties.get("port", 9999), float(context.node.properties.get("timeout", 2)),
        context.session.token)


@registry.register("udp_receive")
def udp_receive(context: HandlerContext):
    data, host, port = context.session.resources.get(context.inputs["endpoint"], "udp").receive(
        int(context.node.properties.get("max_bytes", 65535)),
        float(context.node.properties.get("timeout", 2)), context.session.token)
    return {"data": data, "host": host, "port": port}
