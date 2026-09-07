from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any


def _timeout(value: float) -> float:
    value = float(value)
    if value <= 0 or value > 300:
        raise ValueError(
            "serial timeout must be greater than 0 and at most 300 seconds"
        )
    return value


class SerialConnection:
    def __init__(
        self,
        stream: Any,
        close_command: bytes | None = None,
    ) -> None:
        if (
            close_command is not None
            and (
                not isinstance(close_command, bytes)
                or not close_command
            )
        ):
            raise ValueError(
                "serial close command must be non-empty bytes"
            )

        self.stream = stream
        self.close_command = close_command
        self._closed = False
        self._lock = RLock()
        self._rx_buffer = bytearray()

    def read(self, size: int) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "serial connection is closed"
                )
            return self.stream.read(size)

    def read_incoming(
        self,
        max_lines: int,
        max_bytes: int,
    ) -> list[bytes]:
        """Drain complete newline-terminated lines currently available.

        Production pyserial streams use ``in_waiting`` and therefore read only
        bytes already buffered by the serial driver, avoiding waits for future
        telemetry packets.

        Backends without ``in_waiting`` retain the original readline-based
        behavior for compatibility with existing tests/mocks and adapters.
        """

        max_lines = int(max_lines)
        max_bytes = int(max_bytes)

        if (
            max_lines < 1
            or max_lines > 256
            or max_bytes < 16
            or max_bytes > 65536
        ):
            raise ValueError(
                "serial read bounds are invalid"
            )

        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "serial connection is closed"
                )

            lines: list[bytes] = []

            def extract_complete_lines() -> None:
                while (
                    b"\n" in self._rx_buffer
                    and len(lines) < max_lines
                ):
                    line, _, rest = bytes(
                        self._rx_buffer
                    ).partition(b"\n")

                    lines.append(
                        line + b"\n"
                    )

                    self._rx_buffer = bytearray(
                        rest
                    )

            # Return complete lines already buffered from a previous call.
            extract_complete_lines()

            if len(lines) >= max_lines:
                return lines

            # ====================================================
            # Production pyserial path:
            # use in_waiting so we do NOT block waiting for future
            # telemetry packets.
            # ====================================================
            if hasattr(
                self.stream,
                "in_waiting",
            ):
                try:
                    available = int(
                        self.stream.in_waiting
                    )
                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise TypeError(
                        "serial in_waiting must be an integer"
                    ) from exc

                while (
                    available > 0
                    and len(lines) < max_lines
                ):
                    remaining_capacity = (
                        max_bytes
                        - len(self._rx_buffer)
                    )

                    if remaining_capacity <= 0:
                        raise ValueError(
                            "serial receive buffer exceeds configured bound"
                        )

                    read_size = min(
                        available,
                        remaining_capacity,
                    )

                    raw = self.stream.read(
                        read_size
                    )

                    if not isinstance(
                        raw,
                        (bytes, bytearray),
                    ):
                        raise TypeError(
                            "serial response must be bytes"
                        )

                    if not raw:
                        break

                    self._rx_buffer.extend(
                        raw
                    )

                    if len(self._rx_buffer) > max_bytes:
                        raise ValueError(
                            "serial receive buffer exceeds configured bound"
                        )

                    extract_complete_lines()

                    if len(lines) >= max_lines:
                        break

                    try:
                        available = int(
                            self.stream.in_waiting
                        )
                    except (
                        TypeError,
                        ValueError,
                    ) as exc:
                        raise TypeError(
                            "serial in_waiting must be an integer"
                        ) from exc

                return lines

            # ====================================================
            # Compatibility path:
            # preserve ORIGINAL behavior exactly for mocks/backends
            # that do not provide in_waiting.
            # ====================================================
            while len(lines) < max_lines:
                raw = self.stream.readline(
                    max_bytes + 1
                )

                if not raw:
                    break

                if not isinstance(
                    raw,
                    (bytes, bytearray),
                ):
                    raise TypeError(
                        "serial response must be bytes"
                    )

                self._rx_buffer.extend(
                    raw
                )

                if len(self._rx_buffer) > max_bytes:
                    raise ValueError(
                        "serial receive buffer exceeds configured bound"
                    )

                extract_complete_lines()

            return lines

    def write(self, data: bytes) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "serial connection is closed"
                )
            return self.stream.write(data)

    def query_lines(
        self,
        command: bytes,
        line_count: int,
        max_bytes: int,
    ) -> tuple[bytes, ...]:
        if not isinstance(command, bytes) or not command:
            raise ValueError(
                "serial command must be non-empty bytes"
            )

        line_count = int(line_count)
        max_bytes = int(max_bytes)

        if (
            line_count < 1
            or line_count > 16
            or max_bytes < line_count
            or max_bytes > 65536
        ):
            raise ValueError(
                "serial response bounds are invalid"
            )

        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "serial connection is closed"
                )

            if int(
                self.stream.write(command)
            ) != len(command):
                raise OSError(
                    "incomplete serial command write"
                )

            lines: list[bytes] = []
            remaining = max_bytes

            for _ in range(line_count):
                reader = getattr(
                    self.stream,
                    "readline",
                    None,
                )

                if not callable(reader):
                    raise TypeError(
                        "serial line protocol requires a readline-capable backend"
                    )

                raw = reader(
                    remaining + 1
                )

                if not isinstance(
                    raw,
                    (bytes, bytearray),
                ):
                    raise TypeError(
                        "serial response must be bytes"
                    )

                line = bytes(raw)

                if not line.endswith(b"\n"):
                    raise OSError(
                        "incomplete serial response line"
                    )

                if len(line) > remaining:
                    raise ValueError(
                        "serial response exceeds configured bound"
                    )

                lines.append(
                    line
                )

                remaining -= len(
                    line
                )

            return tuple(
                lines
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return

            self._closed = True

            try:
                self.safe_stop()
            finally:
                self.stream.close()

    def safe_stop(self) -> None:
        with self._lock:
            if self.close_command is None:
                return

            written = int(
                self.stream.write(
                    self.close_command
                )
            )

            if written != len(
                self.close_command
            ):
                raise OSError(
                    "incomplete serial safe-stop write"
                )


class SerialAdapter:
    def __init__(
        self,
        backend: Any = None,
    ) -> None:
        self.backend = backend

    @property
    def available(self) -> bool:
        if self.backend is not None:
            return True

        try:
            import_module(
                "serial"
            )
            return True
        except Exception:
            return False

    def open(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 1,
        close_command: bytes | None = None,
    ) -> Any:
        if (
            not isinstance(port, str)
            or not port.strip()
        ):
            raise ValueError(
                "serial port must be non-empty"
            )

        baudrate = int(
            baudrate
        )

        if (
            baudrate < 1
            or baudrate > 20_000_000
        ):
            raise ValueError(
                "serial baudrate is outside bounds"
            )

        timeout = _timeout(
            timeout
        )

        try:
            backend = (
                self.backend
                or import_module(
                    "serial"
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"pyserial unavailable: {exc}"
            ) from exc

        stream = backend.serial_for_url(
            port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=timeout,
        )

        return SerialConnection(
            stream,
            close_command,
        )
