import socket
import struct
import threading
import unittest
from unittest.mock import patch

from pylabview.execution import CancellationToken
from pylabview.protocols import (MAX_NETWORK_BYTES, ModbusError, ModbusTcpClient,
                                 SerialUnavailableError, TcpConnection, UdpEndpoint,
                                 open_serial)


TOKEN = CancellationToken()


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk: raise EOFError
        data += chunk
    return data


def tcp_server(handler):
    server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0)); server.listen(1)
    port = server.getsockname()[1]
    def run():
        try:
            connection, _ = server.accept()
            with connection: handler(connection)
        finally: server.close()
    thread = threading.Thread(target=run, daemon=True); thread.start()
    return port, thread


class ProtocolV3Tests(unittest.TestCase):
    def test_tcp_exact_read_and_write_loopback(self):
        def handler(sock):
            self.assertEqual(recv_exact(sock, 4), b"ping"); sock.sendall(b"pong")
        port, thread = tcp_server(handler)
        client = TcpConnection.connect("127.0.0.1", port, 1, TOKEN)
        self.assertEqual(client.write(b"ping", 1, TOKEN), 4)
        self.assertEqual(client.read(4, 1, TOKEN, "exactly"), b"pong")
        client.close(); thread.join(1)

    def test_tcp_delimiter_mode(self):
        port, thread = tcp_server(lambda sock: sock.sendall(b"line\nrest"))
        client = TcpConnection.connect("127.0.0.1", port, 1, TOKEN)
        self.assertEqual(client.read(20, 1, TOKEN, "until_delimiter", b"\n"), b"line\n")
        client.close(); thread.join(1)

    def test_tcp_eof_before_exact_size(self):
        port, thread = tcp_server(lambda sock: sock.sendall(b"x"))
        client = TcpConnection.connect("127.0.0.1", port, 1, TOKEN)
        with self.assertRaises(EOFError): client.read(2, 1, TOKEN, "exactly")
        client.close(); thread.join(1)

    def test_network_size_is_bounded(self):
        endpoint = UdpEndpoint.open("127.0.0.1", 0, 1)
        with self.assertRaises(ValueError): endpoint.receive(MAX_NETWORK_BYTES + 1, 1, TOKEN)
        endpoint.close()

    def test_udp_loopback_reports_sender(self):
        receiver = UdpEndpoint.open("127.0.0.1", 0, 1); sender = UdpEndpoint.open("127.0.0.1", 0, 1)
        sender.send(b"hello", *receiver.address, 1, TOKEN)
        data, host, port = receiver.receive(64, 1, TOKEN)
        self.assertEqual(data, b"hello"); self.assertEqual(host, "127.0.0.1"); self.assertEqual(port, sender.address[1])
        sender.close(); receiver.close()

    def _modbus_client(self, responder):
        def handler(sock):
            header = recv_exact(sock, 7); transaction, protocol, length, unit = struct.unpack(">HHHB", header)
            pdu = recv_exact(sock, length - 1); sock.sendall(responder(transaction, protocol, unit, pdu))
        port, thread = tcp_server(handler)
        connection = TcpConnection.connect("127.0.0.1", port, 1, TOKEN)
        return ModbusTcpClient(connection, 1), thread

    def test_modbus_fc03_validates_and_decodes_registers(self):
        def response(transaction, _protocol, unit, pdu):
            self.assertEqual(pdu, b"\x03\x00\x10\x00\x02")
            body = b"\x03\x04\x12\x34\xab\xcd"
            return struct.pack(">HHHB", transaction, 0, len(body) + 1, unit) + body
        client, thread = self._modbus_client(response)
        self.assertEqual(client.read_holding_registers(16, 2, 1, TOKEN), [0x1234, 0xabcd])
        client.close(); thread.join(1)

    def test_modbus_fc06_requires_echo(self):
        def response(transaction, _protocol, unit, pdu):
            self.assertEqual(pdu, b"\x06\x00\x05\x12\x34")
            return struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit) + pdu
        client, thread = self._modbus_client(response)
        self.assertEqual(client.write_single_register(5, 0x1234, 1, TOKEN), 0x1234)
        client.close(); thread.join(1)

    def test_modbus_exception_is_not_converted_to_data(self):
        def response(transaction, _protocol, unit, _pdu):
            body = b"\x83\x02"; return struct.pack(">HHHB", transaction, 0, 3, unit) + body
        client, thread = self._modbus_client(response)
        with self.assertRaisesRegex(ModbusError, "exception 2"): client.read_holding_registers(0, 1, 1, TOKEN)
        client.close(); thread.join(1)

    def test_modbus_transaction_mismatch_is_rejected(self):
        def response(transaction, _protocol, unit, _pdu):
            body = b"\x03\x02\x00\x01"; return struct.pack(">HHHB", transaction + 1, 0, len(body) + 1, unit) + body
        client, thread = self._modbus_client(response)
        with self.assertRaisesRegex(ModbusError, "transaction"): client.read_holding_registers(0, 1, 1, TOKEN)
        client.close(); thread.join(1)

    def test_modbus_quantity_limit(self):
        connection = object.__new__(TcpConnection)
        client = ModbusTcpClient(connection)
        with self.assertRaises(ValueError): client.read_holding_registers(0, 126, 1, TOKEN)

    @patch("pylabview.protocols.importlib.util.find_spec", return_value=None)
    def test_serial_unavailable_is_explicit(self, _find_spec):
        with self.assertRaisesRegex(SerialUnavailableError, "not installed"): open_serial("COM1", 9600, 1)


if __name__ == "__main__": unittest.main()
