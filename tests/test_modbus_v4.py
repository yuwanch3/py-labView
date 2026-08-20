from __future__ import annotations

import unittest

from pylabview.execution import CancellationToken
from pylabview.protocols import ModbusError, ModbusTcpClient


class VectorClient(ModbusTcpClient):
    def __init__(self): self.calls = []
    def _request(self, function, payload, timeout, token):
        self.calls.append((function, payload))
        return self.responses.pop(0)


class ModbusV4Tests(unittest.TestCase):
    def setUp(self): self.client = VectorClient(); self.client.responses = []; self.token = CancellationToken()
    def test_fc01_decodes_lsb_first(self):
        self.client.responses = [bytes((2, 0b10000101, 1))]
        self.assertEqual(self.client.read_coils(0, 9, 1, self.token), [True, False, True, False, False, False, False, True, True])
    def test_fc02_uses_function_two(self):
        self.client.responses = [bytes((1, 3))]; self.assertEqual(self.client.read_discrete_inputs(4, 2, 1, self.token), [True, True]); self.assertEqual(self.client.calls[0][0], 2)
    def test_fc01_quantity_limit(self):
        with self.assertRaises(ValueError): self.client.read_coils(0, 2001, 1, self.token)
    def test_fc01_payload_length_validation(self):
        self.client.responses = [bytes((2, 1))]
        with self.assertRaises(ModbusError): self.client.read_coils(0, 8, 1, self.token)
    def test_fc04_decodes_registers(self):
        self.client.responses = [bytes((4, 0, 1, 0x12, 0x34))]; self.assertEqual(self.client.read_input_registers(0, 2, 1, self.token), [1, 0x1234])
    def test_fc04_quantity_limit(self):
        with self.assertRaises(ValueError): self.client.read_input_registers(0, 126, 1, self.token)
    def test_fc05_true_encoding(self):
        self.client.responses = [bytes((0, 7, 0xff, 0))]; self.assertTrue(self.client.write_single_coil(7, True, 1, self.token)); self.assertEqual(self.client.calls[0][0], 5)
    def test_fc05_rejects_non_boolean(self):
        with self.assertRaises(ValueError): self.client.write_single_coil(0, 1, 1, self.token)
    def test_fc15_packs_lsb_first(self):
        self.client.responses = [bytes((0, 3, 0, 9))]; self.assertEqual(self.client.write_multiple_coils(3, [True, False, True, False, False, False, False, True, True], 1, self.token), 9)
        self.assertEqual(self.client.calls[0][1][-2:], bytes((0x85, 0x01)))
    def test_fc15_response_validation(self):
        self.client.responses = [bytes((0, 0, 0, 1))]
        with self.assertRaises(ModbusError): self.client.write_multiple_coils(3, [True], 1, self.token)
    def test_fc15_type_validation(self):
        with self.assertRaises(ValueError): self.client.write_multiple_coils(0, [1], 1, self.token)
    def test_fc16_encodes_registers(self):
        self.client.responses = [bytes((0, 2, 0, 2))]; self.assertEqual(self.client.write_multiple_registers(2, [1, 0x1234], 1, self.token), 2)
        self.assertEqual(self.client.calls[0][0], 16); self.assertTrue(self.client.calls[0][1].endswith(bytes((0, 1, 0x12, 0x34))))
    def test_fc16_quantity_limit(self):
        with self.assertRaises(ValueError): self.client.write_multiple_registers(0, [0] * 124, 1, self.token)
    def test_fc16_register_validation(self):
        with self.assertRaises(ValueError): self.client.write_multiple_registers(0, [65536], 1, self.token)

    def test_transport_timeout_invalidates_connection(self):
        class Connection:
            def __init__(self): self.closed = False
            def write(self, *args): raise TimeoutError("late")
            def close(self): self.closed = True
        connection = Connection(); client = ModbusTcpClient(connection)
        with self.assertRaises(TimeoutError): client.read_coils(0, 1, 1, self.token)
        self.assertTrue(connection.closed)

    def test_timeout_budget_decreases_across_transport_steps(self):
        class Connection:
            def __init__(self): self.timeouts = []; self.responses = [b"\x00\x01\x00\x00\x00\x04\x01", b"\x01\x01\x01"]
            def write(self, data, timeout, token): self.timeouts.append(timeout); return len(data)
            def read(self, size, timeout, token, mode): self.timeouts.append(timeout); return self.responses.pop(0)
            def close(self): pass
        connection = Connection(); client = ModbusTcpClient(connection)
        self.assertEqual(client.read_coils(0, 1, 1, self.token), [True])
        self.assertTrue(all(later <= earlier for earlier, later in zip(connection.timeouts, connection.timeouts[1:])))


if __name__ == "__main__": unittest.main()
