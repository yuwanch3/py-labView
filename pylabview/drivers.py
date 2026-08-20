"""Hardware abstraction. Only a deterministic simulated DAQ ships built in."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Lock
from typing import Any
import random


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    kind: str
    minimum: float = -10.0
    maximum: float = 10.0


class DAQDriver(ABC):
    @abstractmethod
    def configure(self, channel: ChannelConfig) -> None: ...

    @abstractmethod
    def read(self, channel: str) -> float | bool: ...

    @abstractmethod
    def write(self, channel: str, value: float | bool) -> None: ...


class SimulatedDAQDriver(DAQDriver):
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.channels: dict[str, ChannelConfig] = {}
        self.values: dict[str, float | bool] = {}
        self._lock = Lock()

    def configure(self, channel: ChannelConfig) -> None:
        if channel.kind not in ("analog_input", "analog_output", "digital_input", "digital_output"):
            raise ValueError(f"unsupported channel kind: {channel.kind}")
        if channel.minimum > channel.maximum:
            raise ValueError("minimum must not exceed maximum")
        with self._lock:
            self.channels[channel.name] = channel

    def read(self, channel: str) -> float | bool:
        with self._lock:
            config = self._channel(channel)
            if config.kind == "digital_input":
                return bool(self.values.get(channel, self.rng.choice((False, True))))
            if config.kind != "analog_input":
                return self.values.get(channel, False if "digital" in config.kind else 0.0)
            return self.rng.uniform(config.minimum, config.maximum)

    def write(self, channel: str, value: float | bool) -> None:
        with self._lock:
            config = self._channel(channel)
            if config.kind == "digital_output":
                if not isinstance(value, bool):
                    raise TypeError("digital output requires boolean")
            elif config.kind == "analog_output":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError("analog output requires numeric")
                if not config.minimum <= float(value) <= config.maximum:
                    raise ValueError("analog output is outside configured range")
            else:
                raise ValueError("cannot write an input channel")
            self.values[channel] = value

    def _channel(self, name: str) -> ChannelConfig:
        if name not in self.channels:
            raise ValueError(f"channel is not configured: {name}")
        return self.channels[name]


class DriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[str, DAQDriver] = {}

    def register(self, name: str, driver: DAQDriver) -> None:
        if not name or name in self._drivers:
            raise ValueError(f"driver already registered or invalid: {name}")
        self._drivers[name] = driver

    def get(self, name: str) -> DAQDriver:
        try:
            return self._drivers[name]
        except KeyError as exc:
            raise ValueError(f"unknown DAQ driver: {name}") from exc

    @classmethod
    def with_simulation(cls, rng: random.Random | None = None) -> "DriverRegistry":
        registry = cls()
        registry.register("simulated", SimulatedDAQDriver(rng))
        return registry
