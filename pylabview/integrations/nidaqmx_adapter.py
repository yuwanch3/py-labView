from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any

from ..drivers import ChannelConfig, DAQDriver


MAX_SAMPLES = 1_000_000
MAX_RATE = 10_000_000.0


class NIDAQmxDriver(DAQDriver):
    """NI-DAQmx task adapter. Physical hardware has not been validated by this project."""

    def __init__(self, backend: Any = None) -> None:
        self.backend = backend if backend is not None else import_module("nidaqmx")
        self.channels: dict[str, ChannelConfig] = {}
        self._lock = RLock()

    def configure(self, channel: ChannelConfig) -> None:
        if not channel.name.strip():
            raise ValueError("NI physical channel must be non-empty")
        if channel.kind not in ("analog_input", "analog_output", "digital_input", "digital_output"):
            raise ValueError(f"unsupported NI channel kind: {channel.kind}")
        if channel.minimum >= channel.maximum:
            raise ValueError("minimum must be less than maximum")
        if not 1 <= channel.samples <= MAX_SAMPLES:
            raise ValueError(f"samples must be between 1 and {MAX_SAMPLES}")
        if channel.samples > 1 and channel.kind != "analog_input":
            raise ValueError("finite multi-sample acquisition is supported only for analog input")
        if not 0 < channel.rate <= MAX_RATE:
            raise ValueError(f"rate must be greater than 0 and at most {MAX_RATE}")
        with self._lock:
            self.channels[channel.name] = channel

    def _task(self, config: ChannelConfig) -> Any:
        task = self.backend.Task()
        try:
            channels = task.ai_channels if config.kind == "analog_input" else \
                task.ao_channels if config.kind == "analog_output" else \
                task.di_channels if config.kind == "digital_input" else task.do_channels
            if config.kind == "analog_input":
                channels.add_ai_voltage_chan(config.name, min_val=config.minimum, max_val=config.maximum)
            elif config.kind == "analog_output":
                channels.add_ao_voltage_chan(config.name, min_val=config.minimum, max_val=config.maximum)
            elif config.kind == "digital_input":
                channels.add_di_chan(config.name)
            else:
                channels.add_do_chan(config.name)
            if config.kind == "analog_input" and config.samples > 1:
                acquisition = getattr(getattr(self.backend, "constants", None), "AcquisitionType", None)
                finite = getattr(acquisition, "FINITE", None)
                task.timing.cfg_samp_clk_timing(config.rate, sample_mode=finite, samps_per_chan=config.samples)
            return task
        except BaseException:
            task.close()
            raise

    def read(self, channel: str) -> float | bool | list[float]:
        with self._lock:
            config = self._configured(channel)
            if config.kind not in ("analog_input", "digital_input"):
                raise ValueError("cannot read an output channel")
            task = self._task(config)
            try:
                value = task.read(number_of_samples_per_channel=config.samples, timeout=config.timeout) \
                    if config.samples > 1 else task.read(timeout=config.timeout)
                if config.samples > 1:
                    if (not isinstance(value, (list, tuple)) or len(value) != config.samples
                            or any(isinstance(item, (bool, list, tuple)) or not isinstance(item, (int, float))
                                   for item in value)):
                        raise RuntimeError("NI-DAQmx returned an invalid finite sample payload")
                    return [float(item) for item in value]
                if isinstance(value, (list, tuple)):
                    raise RuntimeError("NI-DAQmx scalar channel returned an ambiguous multi-channel payload")
                if config.kind == "digital_input":
                    if not isinstance(value, bool): raise RuntimeError("NI-DAQmx digital input did not return boolean")
                    return value
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuntimeError("NI-DAQmx analog input did not return numeric")
                return float(value)
            finally:
                task.close()

    def write(self, channel: str, value: float | bool) -> None:
        with self._lock:
            config = self._configured(channel)
            if config.kind not in ("analog_output", "digital_output"):
                raise ValueError("cannot write an input channel")
            if config.kind == "digital_output" and not isinstance(value, bool):
                raise TypeError("digital output requires boolean")
            if config.kind == "analog_output":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError("analog output requires numeric")
                if not config.minimum <= float(value) <= config.maximum:
                    raise ValueError("analog output is outside configured range")
            task = self._task(config)
            try: task.write(value, auto_start=True, timeout=config.timeout)
            finally: task.close()

    def _configured(self, channel: str) -> ChannelConfig:
        try: return self.channels[channel]
        except KeyError as exc: raise ValueError(f"channel is not configured: {channel}") from exc

    def close(self) -> None:
        with self._lock: self.channels.clear()


def discover_devices(backend: Any = None) -> list[str]:
    module = backend if backend is not None else import_module("nidaqmx")
    return [str(getattr(device, "name", device)) for device in module.system.System.local().devices]
