from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import Any, Protocol, runtime_checkable
import errno
import importlib.util
import select
import socket
import struct
import threading
import time

from .execution import CancellationToken


MAX_NETWORK_BYTES = 16 * 1024 * 1024
_RESOLVER_SLOTS = threading.BoundedSemaphore(8)


def _timeout(value: float) -> float:
    value = float(value)
    if value <= 0 or value > 300:
        raise ValueError("network timeout must be greater than 0 and at most 300 seconds")
    return value


def _size(value: int) -> int:
    value = int(value)
    if value < 1 or value > MAX_NETWORK_BYTES:
        raise ValueError(f"network size must be between 1 and {MAX_NETWORK_BYTES}")
    return value


class TcpConnection:
    def __init__(self, sock: socket.socket) -> None:
        self.socket = sock

    @classmethod
    def connect(cls, host: str, port: int, timeout: float, token: CancellationToken) -> "TcpConnection":
        token.check()
        if not host:
            raise ValueError("TCP host must be non-empty")
        port = _integer(port, "TCP port")
        if not 1 <= port <= 65535:
            raise ValueError("TCP port must be between 1 and 65535")
        timeout = _timeout(timeout)
        deadline = time.monotonic() + timeout
        addresses = _resolve(host, port, deadline, token)
        last_error: OSError | None = None
        for family, socktype, proto, _canonical, address in addresses:
            token.check()
            sock = socket.socket(family, socktype, proto)
            try:
                sock.setblocking(False)
                error = sock.connect_ex(address)
                while error not in (0, errno.EISCONN):
                    token.check()
                    if error not in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR):
                        raise OSError(error, "TCP connect failed")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("TCP connect timed out")
                    _readable, writable, exceptional = select.select([], [sock], [sock], min(remaining, 0.05))
                    if not writable and not exceptional:
                        continue
                    error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                token.check()
                sock.setblocking(True)
                sock.settimeout(timeout)
                return cls(sock)
            except (OSError, TimeoutError) as exc:
                sock.close()
                if token.cancelled or isinstance(exc, TimeoutError):
                    raise
                last_error = exc
            except BaseException:
                sock.close()
                raise
        if last_error:
            raise last_error
        raise OSError("TCP host did not resolve to a usable address")

    def write(self, data: bytes, timeout: float, token: CancellationToken) -> int:
        token.check()
        if not isinstance(data, bytes):
            raise TypeError("TCP write requires bytes")
        _size(len(data))
        deadline = time.monotonic() + _timeout(timeout)
        sent = 0
        while sent < len(data):
            token.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("TCP write timed out")
            self.socket.settimeout(min(remaining, 0.05))
            try:
                count = self.socket.send(data[sent:])
            except socket.timeout:
                continue
            if count == 0:
                raise EOFError("TCP peer closed during write")
            sent += count
        token.check()
        return len(data)

    def read(self, size: int, timeout: float, token: CancellationToken, mode: str = "up_to",
             delimiter: bytes = b"\n") -> bytes:
        size = _size(size)
        deadline = time.monotonic() + _timeout(timeout)
        if mode == "up_to":
            return self._recv(size, deadline, token)
        data = bytearray()
        if mode == "exactly":
            while len(data) < size:
                token.check()
                chunk = self._recv(size - len(data), deadline, token)
                if not chunk:
                    raise EOFError("TCP peer closed before requested bytes arrived")
                data.extend(chunk)
            return bytes(data)
        if mode == "until_delimiter":
            if not delimiter or len(delimiter) > 1024:
                raise ValueError("TCP delimiter must contain 1 to 1024 bytes")
            while len(data) < size:
                token.check()
                chunk = self._recv(1, deadline, token)
                if not chunk:
                    raise EOFError("TCP peer closed before delimiter arrived")
                data.extend(chunk)
                if data.endswith(delimiter):
                    return bytes(data)
            raise ValueError("TCP delimiter was not found within size limit")
        raise ValueError(f"unsupported TCP read mode: {mode}")

    def _recv(self, size: int, deadline: float, token: CancellationToken) -> bytes:
        while True:
            token.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("TCP read timed out")
            self.socket.settimeout(min(remaining, 0.05))
            try:
                return self.socket.recv(size)
            except socket.timeout:
                continue

    def close(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()


class UdpEndpoint:
    def __init__(self, sock: socket.socket) -> None:
        self.socket = sock

    @classmethod
    def open(cls, host: str, port: int, timeout: float) -> "UdpEndpoint":
        if not host:
            raise ValueError("UDP bind host must be non-empty; use 0.0.0.0 explicitly for wildcard bind")
        port = _integer(port, "UDP bind port")
        if not 0 <= port <= 65535:
            raise ValueError("UDP port must be between 0 and 65535")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(_timeout(timeout))
            sock.bind((host, port))
            return cls(sock)
        except BaseException:
            sock.close()
            raise

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.socket.getsockname()[:2]
        return str(host), int(port)

    def send(self, data: bytes, host: str, port: int, timeout: float, token: CancellationToken) -> int:
        token.check()
        if not isinstance(data, bytes):
            raise TypeError("UDP send requires bytes")
        _size(len(data))
        port = _integer(port, "UDP destination port")
        if not host or not 1 <= port <= 65535:
            raise ValueError("invalid UDP destination")
        deadline = time.monotonic() + _timeout(timeout)
        while True:
            token.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("UDP send timed out")
            self.socket.settimeout(min(remaining, 0.05))
            try:
                sent = self.socket.sendto(data, (host, port))
                break
            except socket.timeout:
                continue
        token.check()
        return sent

    def receive(self, max_bytes: int, timeout: float, token: CancellationToken) -> tuple[bytes, str, int]:
        token.check()
        max_bytes = _size(max_bytes)
        deadline = time.monotonic() + _timeout(timeout)
        while True:
            token.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("UDP receive timed out")
            self.socket.settimeout(min(remaining, 0.05))
            try:
                data, address = self.socket.recvfrom(max_bytes)
                break
            except socket.timeout:
                continue
        token.check()
        return data, str(address[0]), int(address[1])

    def close(self) -> None:
        self.socket.close()


class ModbusError(RuntimeError):
    pass


class ModbusTcpClient:
    def __init__(self, connection: TcpConnection, unit_id: int = 1) -> None:
        unit_id = _integer(unit_id, "Modbus unit id")
        if not 0 <= unit_id <= 255:
            raise ValueError("Modbus unit id must be between 0 and 255")
        self.connection, self.unit_id, self.transaction_id = connection, unit_id, 0
        self._lock = Lock()
        self._io_started = False

    def _request(self, function: int, payload: bytes, timeout: float, token: CancellationToken) -> bytes:
        with self._lock:
            try:
                return self._request_locked(function, payload, timeout, token)
            except BaseException:
                if self._io_started:
                    try:
                        self.connection.close()
                    except (AttributeError, OSError):
                        pass
                raise
            finally:
                self._io_started = False

    def _request_locked(self, function: int, payload: bytes, timeout: float, token: CancellationToken) -> bytes:
        deadline = time.monotonic() + _timeout(timeout)

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0: raise TimeoutError("Modbus request timed out")
            return value

        token.check()
        self.transaction_id = (self.transaction_id + 1) & 0xffff
        pdu = bytes((function,)) + payload
        frame = struct.pack(">HHHB", self.transaction_id, 0, len(pdu) + 1, self.unit_id) + pdu
        self._io_started = True
        self.connection.write(frame, remaining(), token)
        header = self.connection.read(7, remaining(), token, "exactly")
        transaction, protocol, length, unit = struct.unpack(">HHHB", header)
        if transaction != self.transaction_id:
            raise ModbusError("Modbus transaction id mismatch")
        if protocol != 0:
            raise ModbusError("Modbus protocol id is not zero")
        if unit != self.unit_id:
            raise ModbusError("Modbus unit id mismatch")
        if length < 2 or length > 254:
            raise ModbusError("invalid Modbus length")
        response = self.connection.read(length - 1, remaining(), token, "exactly")
        response_function = response[0]
        if response_function == function | 0x80:
            if len(response) != 2:
                raise ModbusError("malformed Modbus exception response")
            raise ModbusError(f"Modbus exception {response[1]}")
        if response_function != function:
            raise ModbusError("Modbus function mismatch")
        return response[1:]

    def _invalid_response(self, message: str) -> None:
        try:
            self.connection.close()
        except (AttributeError, OSError):
            pass
        raise ModbusError(message)

    def read_holding_registers(self, address: int, quantity: int, timeout: float,
                               token: CancellationToken) -> list[int]:
        address = _integer(address, "FC03 address")
        quantity = _integer(quantity, "FC03 quantity")
        if not 0 <= address <= 65535 or not 1 <= quantity <= 125 or address + quantity > 65536:
            raise ValueError("invalid FC03 address or quantity")
        payload = self._request(3, struct.pack(">HH", address, quantity), timeout, token)
        expected = quantity * 2
        if not payload or payload[0] != expected or len(payload) != expected + 1:
            self._invalid_response("invalid FC03 byte count or payload length")
        return list(struct.unpack(">" + "H" * quantity, payload[1:]))

    def read_coils(self, address: int, quantity: int, timeout: float, token: CancellationToken) -> list[bool]:
        return self._read_bits(1, address, quantity, timeout, token)

    def read_discrete_inputs(self, address: int, quantity: int, timeout: float,
                             token: CancellationToken) -> list[bool]:
        return self._read_bits(2, address, quantity, timeout, token)

    def _read_bits(self, function: int, address: int, quantity: int, timeout: float,
                   token: CancellationToken) -> list[bool]:
        address = _integer(address, f"FC{function:02d} address")
        quantity = _integer(quantity, f"FC{function:02d} quantity")
        if not 0 <= address <= 65535 or not 1 <= quantity <= 2000 or address + quantity > 65536:
            raise ValueError(f"invalid FC{function:02d} address or quantity")
        payload = self._request(function, struct.pack(">HH", address, quantity), timeout, token)
        expected = (quantity + 7) // 8
        if not payload or payload[0] != expected or len(payload) != expected + 1:
            self._invalid_response(f"invalid FC{function:02d} byte count or payload length")
        return [bool(payload[1 + index // 8] & (1 << (index % 8))) for index in range(quantity)]

    def read_input_registers(self, address: int, quantity: int, timeout: float,
                             token: CancellationToken) -> list[int]:
        address = _integer(address, "FC04 address"); quantity = _integer(quantity, "FC04 quantity")
        if not 0 <= address <= 65535 or not 1 <= quantity <= 125 or address + quantity > 65536:
            raise ValueError("invalid FC04 address or quantity")
        payload = self._request(4, struct.pack(">HH", address, quantity), timeout, token)
        expected = quantity * 2
        if not payload or payload[0] != expected or len(payload) != expected + 1:
            self._invalid_response("invalid FC04 byte count or payload length")
        return list(struct.unpack(">" + "H" * quantity, payload[1:]))

    def write_single_coil(self, address: int, value: bool, timeout: float, token: CancellationToken) -> bool:
        address = _integer(address, "FC05 address")
        if not 0 <= address <= 65535 or not isinstance(value, bool): raise ValueError("invalid FC05 address or coil value")
        request = struct.pack(">HH", address, 0xff00 if value else 0)
        if self._request(5, request, timeout, token) != request: self._invalid_response("FC05 response does not echo request")
        return value

    def write_multiple_coils(self, address: int, values: list[bool], timeout: float,
                             token: CancellationToken) -> int:
        address = _integer(address, "FC15 address")
        if not isinstance(values, list) or not 1 <= len(values) <= 1968 or any(not isinstance(value, bool) for value in values):
            raise ValueError("FC15 values must contain 1 to 1968 booleans")
        if not 0 <= address <= 65535 or address + len(values) > 65536: raise ValueError("invalid FC15 address range")
        packed = bytearray((len(values) + 7) // 8)
        for index, value in enumerate(values):
            if value: packed[index // 8] |= 1 << (index % 8)
        request = struct.pack(">HHB", address, len(values), len(packed)) + packed
        response = self._request(15, request, timeout, token)
        if response != struct.pack(">HH", address, len(values)): self._invalid_response("invalid FC15 response")
        return len(values)

    def write_multiple_registers(self, address: int, values: list[int], timeout: float,
                                 token: CancellationToken) -> int:
        address = _integer(address, "FC16 address")
        if not isinstance(values, list) or not 1 <= len(values) <= 123: raise ValueError("FC16 requires 1 to 123 registers")
        registers = [_integer(value, "FC16 register") for value in values]
        if any(not 0 <= value <= 65535 for value in registers) or not 0 <= address <= 65535 or address + len(values) > 65536:
            raise ValueError("invalid FC16 address or register value")
        request = struct.pack(">HHB", address, len(values), len(values) * 2) + struct.pack(">" + "H" * len(values), *registers)
        response = self._request(16, request, timeout, token)
        if response != struct.pack(">HH", address, len(values)): self._invalid_response("invalid FC16 response")
        return len(values)

    def write_single_register(self, address: int, value: int, timeout: float,
                              token: CancellationToken) -> int:
        address = _integer(address, "FC06 address")
        value = _integer(value, "FC06 value")
        if not 0 <= address <= 65535 or not 0 <= value <= 65535:
            raise ValueError("invalid FC06 address or register value")
        request = struct.pack(">HH", address, value)
        payload = self._request(6, request, timeout, token)
        if payload != request:
            self._invalid_response("FC06 response does not echo request")
        return value

    def close(self) -> None:
        self.connection.close()


class SerialUnavailableError(RuntimeError):
    pass


def pyserial_available() -> bool:
    return importlib.util.find_spec("serial") is not None


def open_serial(port: str, baudrate: int, timeout: float) -> Any:
    if not pyserial_available():
        raise SerialUnavailableError("pyserial adapter is not installed")
    import serial  # type: ignore[import-not-found]
    return serial.serial_for_url(port, baudrate=int(baudrate), timeout=_timeout(timeout),
                                 write_timeout=_timeout(timeout))


@dataclass(frozen=True)
class OpcUaCapabilities:
    available: bool = False
    read: bool = False
    write: bool = False
    subscriptions: bool = False
    reason: str = "OPC UA adapter is not installed; core provides only an adapter contract"


@runtime_checkable
class OpcUaAdapter(Protocol):
    @property
    def capabilities(self) -> OpcUaCapabilities: ...

    def connect(self, endpoint: str, timeout: float, token: CancellationToken) -> Any: ...

    def read(self, connection: Any, node_ids: list[str], timeout: float,
             token: CancellationToken) -> list[Any]: ...

    def close(self, connection: Any) -> None: ...


try:
    _asyncua_available = importlib.util.find_spec("asyncua.sync") is not None
except (ImportError, ModuleNotFoundError, ValueError):
    _asyncua_available = False
OPCUA_CAPABILITIES = OpcUaCapabilities(
    available=_asyncua_available, read=_asyncua_available, write=_asyncua_available,
    reason=("asyncua sync adapter available; subscriptions are not implemented" if _asyncua_available
            else "asyncua adapter is not installed"),
)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _resolve(host: str, port: int, deadline: float, token: CancellationToken) -> list[tuple[Any, ...]]:
    while not _RESOLVER_SLOTS.acquire(timeout=0.05):
        token.check()
        if time.monotonic() >= deadline:
            raise TimeoutError("TCP hostname resolution timed out")
    results: Queue[tuple[list[tuple[Any, ...]] | None, BaseException | None]] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            results.put((addresses, None))
        except BaseException as exc:
            results.put((None, exc))
        finally:
            _RESOLVER_SLOTS.release()

    threading.Thread(target=resolve, name="pylabview-dns-resolver", daemon=True).start()
    while True:
        token.check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("TCP hostname resolution timed out")
        try:
            addresses, error = results.get(timeout=min(remaining, 0.05))
        except Empty:
            continue
        if error:
            raise error
        return addresses or []
