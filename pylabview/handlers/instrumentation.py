from __future__ import annotations

from ..protocols import MAX_NETWORK_BYTES, ModbusTcpClient, TcpConnection
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


def _resource(context: HandlerContext, kind: str, create):
    return context.runtime._session_resource(context.session, context.caller_vi, context.node,
                                             kind, context.graph_scope, create)


@registry.register("modbus_connect")
def modbus_connect(context: HandlerContext):
    return _resource(context, "modbus", lambda: context.session.resources.add("modbus", ModbusTcpClient(
        TcpConnection.connect(str(context.node.properties.get("host", "127.0.0.1")),
                              context.node.properties.get("port", 502),
                              float(context.node.properties.get("timeout", 2)), context.session.token),
        context.node.properties.get("unit_id", 1))))


@registry.register("modbus_read_holding", "modbus_read_coils", "modbus_read_discrete", "modbus_read_input")
def modbus_read(context: HandlerContext):
    methods = {
        "modbus_read_holding": "read_holding_registers",
        "modbus_read_coils": "read_coils",
        "modbus_read_discrete": "read_discrete_inputs",
        "modbus_read_input": "read_input_registers",
    }
    client = context.session.resources.get(context.inputs["client"], "modbus")
    return getattr(client, methods[context.node.type])(
        context.node.properties.get("address", 0), context.node.properties.get("quantity", 1),
        float(context.node.properties.get("timeout", 2)), context.session.token)


@registry.register("modbus_write_register", "modbus_write_coil", "modbus_write_coils", "modbus_write_registers")
def modbus_write(context: HandlerContext):
    methods = {
        "modbus_write_register": "write_single_register",
        "modbus_write_coil": "write_single_coil",
        "modbus_write_coils": "write_multiple_coils",
        "modbus_write_registers": "write_multiple_registers",
    }
    value = context.inputs["values"] if context.node.type in ("modbus_write_coils", "modbus_write_registers") else context.inputs["value"]
    client = context.session.resources.get(context.inputs["client"], "modbus")
    return getattr(client, methods[context.node.type])(
        context.node.properties.get("address", 0), value,
        float(context.node.properties.get("timeout", 2)), context.session.token)


@registry.register("serial_open")
def serial_open(context: HandlerContext):
    return _resource(context, "serial", lambda: context.session.resources.add("serial", context.runtime.serial.open(
        str(context.node.properties.get("port", "COM1")), int(context.node.properties.get("baudrate", 9600)),
        float(context.node.properties.get("timeout", 1)))))


@registry.register("serial_read")
def serial_read(context: HandlerContext):
    size = context.runtime._bounded_int(context.node, "size", 1024)
    if size < 1 or size > MAX_NETWORK_BYTES:
        from ..runtime import DataflowError
        raise DataflowError("serial size is outside bounds")
    data = context.session.resources.get(context.inputs["connection"], "serial").read(size)
    if len(data) > size:
        from ..runtime import DataflowError
        raise DataflowError("serial backend exceeded requested size")
    if context.node.properties.get("mode", "bytes") == "text":
        return bytes(data).decode(str(context.node.properties.get("encoding", "utf-8")))
    return bytes(data)


@registry.register("serial_write")
def serial_write(context: HandlerContext):
    data = context.inputs["data"]
    if context.node.properties.get("mode", "bytes") == "text":
        data = str(data).encode(str(context.node.properties.get("encoding", "utf-8")))
    if not isinstance(data, bytes):
        from ..runtime import DataflowError
        raise DataflowError("serial bytes mode requires bytes")
    if not 1 <= len(data) <= MAX_NETWORK_BYTES:
        from ..runtime import DataflowError
        raise DataflowError("serial write size is outside bounds")
    return int(context.session.resources.get(context.inputs["connection"], "serial").write(data))


@registry.register("serial_close")
def serial_close(context: HandlerContext):
    context.session.resources.close(context.inputs["connection"])
    return None


@registry.register("visa_open")
def visa_open(context: HandlerContext):
    return _resource(context, "visa", lambda: context.session.resources.add("visa", context.runtime.visa.open(
        str(context.node.properties.get("resource", "")), float(context.node.properties.get("timeout", 2)),
        int(context.node.properties.get("max_bytes", 1048576)))))


@registry.register("visa_write", "visa_query", "visa_read_raw", "visa_write_raw")
def visa_operation(context: HandlerContext):
    instrument = context.session.resources.get(context.inputs["instrument"], "visa")
    operations = {
        "visa_write": lambda: instrument.write(context.inputs["text"]),
        "visa_query": lambda: instrument.query(context.inputs["text"]),
        "visa_read_raw": instrument.read_raw,
        "visa_write_raw": lambda: instrument.write_raw(context.inputs["data"]),
    }
    return operations[context.node.type]()


@registry.register("visa_close")
def visa_close(context: HandlerContext):
    context.session.resources.close(context.inputs["instrument"])
    return None


@registry.register("opcua_connect")
def opcua_connect(context: HandlerContext):
    return _resource(context, "opcua", lambda: context.session.resources.add("opcua", context.runtime.opcua.connect(
        str(context.node.properties.get("endpoint", "")), float(context.node.properties.get("timeout", 2)))))


@registry.register("opcua_read")
def opcua_read(context: HandlerContext):
    return context.session.resources.get(context.inputs["connection"], "opcua").read(
        str(context.node.properties.get("node_id", "")))


@registry.register("opcua_write")
def opcua_write(context: HandlerContext):
    context.session.resources.get(context.inputs["connection"], "opcua").write(
        str(context.node.properties.get("node_id", "")), context.inputs["value"])
    return None


@registry.register("opcua_disconnect")
def opcua_disconnect(context: HandlerContext):
    context.session.resources.close(context.inputs["connection"])
    return None
